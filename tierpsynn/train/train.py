# %%

import argparse
import pickle
from argparse import ArgumentParser
from collections import namedtuple
from functools import partial
from pathlib import Path

import h5py
import jax
import jax.numpy as jnp
import jax.random as jr
import matplotlib.pyplot as plt
import numpy as np
import optax
from deeptangle import build_model, checkpoints, utils
from deeptangle.dataset import pca
from jax import grad, jit, lax, pmap, vmap
from jax.tree_util import tree_map, tree_reduce

TrainState = utils.NetState
Losses = namedtuple("Losses", ["w", "s", "p"])
import random

import numpy as np
import tqdm
from skimage.transform import resize

# data_dir ='/home/weheliye@cscdom.csc.mrc.ac.uk/behavgenom_mnt/Group_Annotation/Final_training_data'
# %%


def train_data(
    data_dir, npca=92, cutoff=96, sigma=15, epochs=200, pret_trained_model=None
):

    load = pret_trained_model
    cutoff = cutoff
    sigma = sigma
    num_steps = epochs
    seed = 42
    learning_rate = 0.001
    nframes = 11
    size = int(512)
    n_suggestions = 8
    latent_dim = 8
    npca = npca
    wloss_w = 1
    wloss_s = 1e2
    wloss_p = 1e5
    save = True

    rootdir = Path(data_dir)

    filepath_training = list(rootdir.glob("*.hdf5"))[0]
    filepath_pca_transformation = list(rootdir.glob("*.npy"))[0]

    parameters_file_name = filepath_training.parts[-1].split(".")[0]
    experiment_dir = rootdir.joinpath(
        "models",
        f"parameters_multi_worms_{parameters_file_name}_pca_{npca}_epochs_{epochs}",
    )
    path = experiment_dir

    path.mkdir(parents=True, exist_ok=True)

    def _optimizer():
        return optax.adamw(learning_rate=learning_rate)

    @partial(jit, static_argnames="forward")
    def init_network(rng_key, forward) -> TrainState:
        """
        Initialises the weights of the network with dummy data to map the shapes
        of the hidden layers.
        """
        X_init = jnp.ones((1, nframes, size, size))
        params, state = forward.init(rng_key, X_init, is_training=True)
        opt_state = _optimizer().init(params)
        return TrainState(params, state, opt_state)

    def _importance_weights(n: int) -> jnp.ndarray:
        weights = 1 / (jnp.abs(jnp.arange(-n // 2 + 1, n // 2 + 1)) + 1)
        return weights / weights.sum()

    def multi_loss_fn(Y_pred, Y_label):
        X_pred, S_pred, P_pred = Y_pred

        inside = jnp.all((Y_label >= 0) & (Y_label < size), axis=(-1, -2, -3))

        @vmap
        def distace_matrix(a, b):
            A = a[None, ...]
            B = b[:, None, ...]
            return jnp.sum((A - B) ** 2, axis=-1)

        # Compute the distance matrix for direct and flip versions
        distance = distace_matrix(X_pred, Y_label).mean(-1)
        flip_distance = distace_matrix(X_pred, jnp.flip(Y_label, axis=-2)).mean(-1)
        distances = jnp.minimum(distance, flip_distance)

        # Reduce the distance to be weighted by the importance of each frame.
        num_frames = X_pred.shape[2]
        # temporal_weights = jnp.repeat(0.5,num_frames)
        # print(num_frames)
        temporal_weights = _importance_weights(num_frames)
        distances = jnp.average(distances, axis=-1, weights=temporal_weights)

        # Compute the loss of the points only taking into consideration only those
        # predictions that are inside.
        inside_count = jnp.sum(inside) + 1e-6
        masked_distances = distances * inside[:, :, None]
        Loss_X = jnp.sum(jnp.min(masked_distances, axis=2)) / inside_count

        # Before computing the score and latent space losses,
        # we stop gradients for of the distances.
        distances = jax.lax.stop_gradient(distances)
        X = jax.lax.stop_gradient(X_pred)

        # Compute the confidence score of each prediction as S = exp(-d2/sigma)
        # and perform L2 loss.
        scores = jnp.exp(-jnp.min(distances, axis=1) / sigma)
        Loss_S = jnp.mean((scores - S_pred) ** 2)

        # Find out which target is closests to each prediction.
        # ASSUMPTION: That is the one they are predicting.
        T = jnp.argmin(distances, axis=1)

        # Compute which permutations are targeting the same index on a matrix.
        # T(i,j) = T(j, i) = 1 if i,j 'target' the same label, 0 otherwise
        same_T = T[:, None, :] == T[:, :, None]

        # Visibility mask for far predictions that not should not share latent
        # space.
        distance_ls = distace_matrix(P_pred, P_pred)
        K = X.shape[3]
        Xcm = X[:, :, num_frames // 2, K // 2, :]  # [B N Wt K 2]
        visible = distace_matrix(Xcm, Xcm) < cutoff**2
        factor = visible / visible.sum(axis=2)[:, :, None]

        # Compute the cross entropy loss depending on whether they aim to predict
        # the same target. P(i targets k| j targets k) ~= e^(-d^2)
        # https://jax.readthedocs.io/en/latest/faq.html#gradients-contain-nan-where-using-where
        safe_log = lambda x: jnp.log(jnp.where(x > 0.0, x, 1.0))
        atraction = distance_ls  # log(exp(d2))
        repulsion = -safe_log(1 - jnp.exp(-distance_ls))
        Loss_P = factor * jnp.where(same_T, atraction, repulsion)

        # Only take into account the predictions that are actually preddicting.
        # Bad prediction should not be close to actual predictions in the latent
        # space.
        scores_matrix = scores[:, :, None] * scores[:, None, :]
        Loss_P = jnp.sum(scores_matrix * Loss_P) / scores_matrix.sum()
        return Losses(Loss_X, Loss_S, Loss_P)

    def loss_fn(forward, params, state, inputs, targets):
        preds, state = forward.apply(params, state, inputs, is_training=True)

        # Compute the losses and average over the batch.
        total_losses = multi_loss_fn(preds, targets)

        # Weight the losses with the given HP and
        # compute total loss as a sum of losses.
        weights = Losses(wloss_w, wloss_s, wloss_p)
        total_losses = tree_map(jnp.multiply, weights, total_losses)
        loss = tree_reduce(jnp.add, total_losses)
        return loss, (state, total_losses)

    grad_fn = jit(grad(loss_fn, argnums=1, has_aux=True), static_argnames="forward")

    @partial(pmap, axis_name="i", static_broadcasted_argnums=0, donate_argnums=1)
    def train_step(forward, train_state, inputs, targets):
        # Unpack the train state and compute gradients w.r.t the parameters.
        params, state, opt_state = train_state
        grads, (state, losses) = grad_fn(forward, params, state, inputs, targets)

        # Use the mean of the gradient across replicas if the model is in
        # a distributed training.
        grads = lax.pmean(grads, axis_name="i")

        # Update the parameters by using the optimizer.
        updates, opt_state = _optimizer().update(grads, opt_state, params=params)
        params = optax.apply_updates(params, updates)

        # Loss should be the mean of all the losses too (only affects logging.)
        losses = lax.pmean(losses, axis_name="i")

        new_train_state = TrainState(params, state, opt_state)
        return losses, new_train_state

    init_key, data_key, train_key = jr.split(jr.PRNGKey(seed), num=3)

    def save_A_matrix(path, A):
        with path.joinpath("eigenworms_transform.npy").open("wb") as f:
            jnp.save(f, A, allow_pickle=False)

    def save_state(path, state):
        with path.joinpath("arrays.npy").open("wb") as f:
            for x in jax.tree_util.tree_leaves(state):
                jnp.save(f, x, allow_pickle=False)

        tree_struct = jax.tree_util.tree_map(lambda _: 0, state)
        with path.joinpath("tree.pkl").open("wb") as f:
            pickle.dump(tree_struct, f)

    def _multi_worm_training_data(filepath_training):
        with h5py.File(filepath_training, "r+") as f:
            arrays_group = f["x_train"]
            y_arrays_group = f["y_train"]
            length_of_data = len(list(arrays_group))
            gen_label = random.sample(list(arrays_group), len(list(arrays_group)))
            for k in range(0, length_of_data - 1, 2):
                X = jnp.maximum(
                    arrays_group[f"{gen_label[k]:05}"][:],
                    arrays_group[f"{gen_label[k+1]:05}"][:],
                )
                y = jnp.concatenate(
                    [
                        y_arrays_group[f"{gen_label[k]:05}"][:],
                        y_arrays_group[f"{gen_label[k+1]:05}"][:],
                    ],
                    axis=0,
                )
                yield X, y

    def _return_length_data(filepath_training):
        with h5py.File(filepath_training, "r+") as f:
            arrays_group = f["x_train"]
            length_of_data = len(arrays_group)
        return length_of_data

    with open(Path(filepath_pca_transformation), "rb") as f:
        y_train = np.load(f)

    n_suggestions = 8
    latent_dim = 8
    if load:
        with Path(load).joinpath("eigenworms_transform.npy").open("rb") as f:
            A = jnp.load(f)
        forward_fn = build_model(A, n_suggestions, latent_dim, nframes)
        state = checkpoints.restore(load, broadcast=False)
        print("Data drawn from loaded database")
    else:
        net_key, _ = jr.split(init_key, 2)

        A = pca.init_pca_train_data(y_train, n_components=npca)
        forward_fn = build_model(A, n_suggestions, latent_dim, nframes)
        state = init_network(net_key, forward_fn)
        state = utils.broadcast_sharded(state, jax.local_device_count())

    save_A_matrix(path, A)
    length_of_data = _return_length_data(filepath_training) / 2
    losses = [Losses(w=1e9, s=1e9, p=1e9)] * int(length_of_data)
    warm_up = 1

    saved_loss = 1e9
    print(f"number of labels {int(length_of_data)}")

    for step in tqdm.tqdm((range(num_steps))):
        dataset = _multi_worm_training_data(filepath_training)

        for k, (X, y) in enumerate(dataset):

            X_batch = jnp.array((X[None, None, :]))
            y_batch = jnp.array(y[None, None, :])

            train_loss, state = train_step(forward_fn, state, X_batch, y_batch)
            losses[k] = train_loss

            if k % int(length_of_data) == 0:
                losses = tree_map(jnp.mean, jax.device_get(losses))
                loss = tree_reduce(jnp.add, losses) / len(losses)
                avg = tree_map(lambda *a: jnp.average(jnp.array(a)), *losses)
                logl = {"loss": loss, "w": avg.w, "s": avg.s, "p": avg.p}

                if save := (loss < saved_loss and step > warm_up):

                    saved_loss = loss
                    save_state(path, state)
                    print(k, step, logl["loss"], "saved model")

    print("Training complete!!!!")


def process_main_train():
    parser = argparse.ArgumentParser(description="Train DT_C model.")
    parser.add_argument("--data_dir", type=str, help="Path to the input video file")
    parser.add_argument("--npca", type=int, help="PCA parameters.")
    parser.add_argument("--cutoff", type=int, default=96, help="Cut of distance.")
    parser.add_argument(
        "--sigma", type=int, default=15, help="Sigma for calculating the scores."
    )
    parser.add_argument("--epochs", type=int, default=200, help="Number of steps")
    parser.add_argument(
        "--model_dir", type=str, default=None, help="Path to the pre-trained model"
    )

    args = parser.parse_args()
    train_data(
        args.data_dir, args.npca, args.cutoff, args.sigma, args.epochs, args.model_dir
    )


if __name__ == "__main__":
    process_main_train()
