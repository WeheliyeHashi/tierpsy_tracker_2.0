# -*- coding: utf-8 -*-
"""
Created on Wed Aug 10 19:59:08 2016

@author: ajaver
"""
import errno
import fnmatch
import os
import sys

from tierpsy.helper.misc import IMG_EXT, RESERVED_EXT, replace_subdir
from tierpsy.helper.params.tracker_param import valid_options


def filter_img_directories(fnames):
    """
    This is my version to filter directory with images.
    by only selecting the first image.
    """
    ext_d = {}
    for fname in fnames:
        f_ext = os.path.splitext(fname)[1]
        if not f_ext in ext_d:
            ext_d[f_ext] = []
        ext_d[f_ext].append(fname)

    fnames_filtered = []
    for f_ext, f_list in ext_d.items():
        if f_ext in IMG_EXT:
            # only select the first image if there are images in the directory
            f_list = [min(f_list)]
        fnames_filtered += f_list

    return fnames_filtered


def find_valid_files(root_dir, pattern_include=["*"], pattern_exclude=""):
    """
    Recursively find the files in root_dir that
    match pattern_include and do not match pattern_exclude .
    """

    # input validation
    invalid_ext = ["*" + x for x in RESERVED_EXT]
    if not pattern_exclude:
        pattern_exclude = []
    elif not isinstance(pattern_exclude, (list, tuple)):
        pattern_exclude = [pattern_exclude]
    pattern_exclude += invalid_ext

    # real processing
    root_dir = os.path.abspath(root_dir)
    if not os.path.exists(root_dir):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), root_dir)
    # if there is only a string (only one pattern) let's make it a list to be
    # able to reuse the code
    if not isinstance(pattern_include, (list, tuple)):
        pattern_include = [pattern_include]
    if not isinstance(pattern_exclude, (list, tuple)):
        pattern_exclude = [pattern_exclude]

    valid_files = []
    for dpath, dnames, fnames in os.walk(root_dir):
        fnames = filter_img_directories(fnames)

        for fname in fnames:
            good_patterns = any(fnmatch.fnmatch(fname, dd) for dd in pattern_include)
            bad_patterns = any(fnmatch.fnmatch(fname, dd) for dd in pattern_exclude)
            if good_patterns and not bad_patterns:
                fullfilename = os.path.abspath(os.path.join(dpath, fname))
                assert os.path.exists(fullfilename)
                valid_files.append(fullfilename)

    return valid_files


def create_script(base_cmd, args, argkws):
    """
    Produce string as command line arguments in the form:

    base_cmd arg1 ... --argkw_key1 argkw_val1 ...
    """
    base_cmd = [x for x in base_cmd if x]

    cmd = base_cmd + args
    for key, dat in argkws.items():
        if isinstance(dat, bool):
            if dat:
                cmd.append("--" + key)
        elif isinstance(dat, (list, tuple)):
            cmd += ["--" + key] + list(dat)
        else:
            cmd += ["--" + key, str(dat)]
    return cmd


def get_real_script_path(fullfile, base_name=""):
    """get the path name that works with pyinstaller binaries"""
    try:
        if not base_name:
            base_name = os.path.splitext(os.path.basename(fullfile))[0]
        # use this directory if it is a one-file produced by pyinstaller
        exec_fname = os.path.join(sys._MEIPASS, base_name)
        if os.name == "nt":
            exec_fname += ".exe"
        return [exec_fname]
    except AttributeError:
        return [sys.executable, os.path.realpath(fullfile)]


def remove_border_checkpoints(list_of_points, last_valid, index):
    assert (index == 0) or (
        index == -1
    )  # decide if start removing from the begining or the end
    if last_valid and last_valid in list_of_points:
        while list_of_points and list_of_points[index] != last_valid:
            list_of_points.pop(index)


def get_results_dir(mask_files_dir):
    return replace_subdir(mask_files_dir, "MaskedVideos", "Results")


def get_masks_dir(videos_dir):
    if "Worm_Videos" in videos_dir:
        return replace_subdir(videos_dir, "Worm_Videos", "MaskedVideos")
    else:
        return replace_subdir(videos_dir, "RawVideos", "MaskedVideos")


# %%

if __name__ == "__main__":
    dname = "/Users/ajaver/OneDrive - Imperial College London/paper_tierpsy_tracker/benchmarks/"
    v_files = find_valid_files(dname, pattern_include="*.avi")
    print(v_files)
