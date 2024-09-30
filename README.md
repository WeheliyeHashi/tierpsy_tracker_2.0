# Tierpsy Tracker 

## How the model works

For the DeepTangle Crawling (DT_C) model, the training dataset was curated in several stages. Initially, isolated worm clips from Tierpsy were organized into sequences of 2, 4, or 6 seconds, arranged in a grid of rows and columns. Each training clip had dimensions of 11x512x512 pixels. This process produced a total of 50,000 clips, each containing 6-8 worms, depending on their spatial distribution. The input images for training featured dark backgrounds to simulate overlapping worms by stacking two images together.

To address the challenge of detecting coiling worms, which Tierpsy struggles to capture effectively, we manually annotated over 1,000 clips of coiled worms using our in-house GUI (https://github.com/WeheliyeHashi/Worm_annotation.git). These annotations were crucial for teaching the model to recognize and learn coiling postures.

The training code was adapted from the work of Alonso and Kirkegaard [1]. Training was conducted on an NVIDIA RTX A6000 with 48 GB of RAM. The model was implemented using JAX, with the Adam optimization algorithm, a learning rate of 0.001, and ResNet as the backbone architecture [1]. The latent dimension was set to 8, and the maximum number of splines per grid was also set to 8. A cutoff distance of 48 pixels was applied during training, and the Principal Component Analysis (PCA) dimension was set to 36, a higher value than that used for swimming cases [1], due to the unique postures of crawling worms.

The PCA transformation matrix was constructed using splines from both the training clips and instance segmentation data, specifically from crawling worms. As the model is based on a YOLO algorithm, it produces spline predictions, confidence scores, and latent space outputs. The output shape for the spline predictions was (32, 32, 8, 3, 36), corresponding to a 32x32 grid, with each cell measuring 16x16 pixels. Each cell contains 8 predicted splines across three central frames of the input stack, along with 36 PCA components. To convert these PCA components into real-space coordinates, we multiplied them by the PCA transformation matrix derived from the crawling worm splines. The output shape for confidence scores was (32, 32, 8), and for latent space outputs, it was (32, 32, 8, 8).

## Inference 

To avoid shifting the predicted splines relative to the worm centerline, the input images were padded so that the image resolution was a multiple of 16. For brightfield experiments, the background was removed by calculating the mean of all video frames and subtracting this from all input clips. For fluorescent imaging, the input images were used without preprocessing.

Since many of the videos tracked in Hydra are 5 minutes long at 25 fps, some frames were skipped during detection to improve processing speed. In this case, we skipped 3 frames, which allowed faster skeleton detection per video. Once all skeletons were detected, we used the tracking technique described by Alonso and Kirkegaard [1].

To recover the skeletons for the skipped frames, we used 3D spline interpolation that considered x, y, and time coordinates. We divided the detected splines into chunks of 10, allowing a maximum gap of 6 frames. Each chunk was interpolated using a spline parameter of Ma = 6 for time and Mb = 10 for space. After recovering the missing skeletons, features were extracted based on those generated by the Tierpsy Tracker [2]. The output features were compatible with the Tierpsy Tracker viewer.

For videos with lower frame rates, we recommend direct detection of each frame rather than skipping frames, as skipping frames at lower fps results in a higher root mean square error between the actual and predicted skeletons, particularly at the worm's head, where there is a high degree of movement.

[1] Fast spline detection in high-density microscopy data
[2] Tierpsy Tracker paper

The code runs on *.yaml, *.mp4, and *.hdf5 files only.

## Installations 

In the current study, we used CUDA 11.4 and cuDNN 8.6. We downloaded JAX from:
https://storage.googleapis.com/jax-releases/jax_cuda_releases.html

You must download the correct version of JAX for your Python version, CUDA, and cuDNN.

```bash
conda create -n DT_C python=3.10
conda activate DT_C
```
```bash
pip install jaxlib-0.4.13+cuda11.cudnn86-cp310-cp310-manylinux2014_x86_64.whl
pip install jax==0.4.13
pip install -r requirements_local
pip install -e .
```

For the HPC we used cuda 12.1 and cudnn 8.9.  
```bash
conda create -n DT_C python=3.10
conda activate DT_C
pip install jaxlib-0.4.13+cuda12.cudnn89-cp310-cp310-manylinux2014_x86_64.whl
pip install jax==0.4.13
conda install -c conda-forge opencv
pip install -r requirements_hpc.txt
pip install -e .
```


If you want to use a different Python version (i.e., one different from Python 3.9 or Python 3.10), please run this code:


```bash
cd tierpsy_tracker_2.0/tierpsynn/extras/cython_files
python setup.py build_ext --inplace
```

To ensure installation was successful, please run the following command when the DT_C environment is active:

```bash
ProcessLocal --help
```


## Evaluation

```bash
ProcessLocal  [--input_vid INPUT_VID] --params_well PARAMS_WELL
                    [--apply_spline APPLY_SPLINE]
                    [--process_type PROCESS_TYPE]
                    [--track_detect TRACK_DETECT]
                    [--post_process POST_PROCESS]
                    [--file_extension FILE_EXTENSION]
```
input_vid: Path to your videos (e.g., 'Path_to_your_videos/RawVideos/').

params_well: Path to your parameters JSON file. Please use the example JSON file provided in tierpsynn/extras/json_params_example/Test_params.json.

apply_spline: This is a boolean value. Typically, you apply it when skipping frames (e.g., when you have high FPS). For low FPS, it's best to avoid skipping frames.

process_type: Either "local" or "HPC". If running locally, set this to "local". If using an HPC, set it to "HPC". Use the example qfiles provided for HPC analysis.

track_detect: This is a boolean value to detect skeletons only.

post_process: This is a boolean value. It creates the features based on Tierpsy Tracker 1.0 and can only be done if skeletons are available.

file_extension: There are three options: "*.mp4", ".hdf5", or "*.yaml".
Example of running


ProcessLocal --input_vid 'Data/transfer_2833382_files_c35b8490/RawVideos' --params_well 'Data/transfer_2833382_files_c35b8490/loopbio_rig_6WP_splitFOV_NN_20220202.json' --process_type 'local' --apply_spline True  --post_process True --track_detect True --file_extension "*.mp4"



