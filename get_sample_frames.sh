#!/bin/sh
# Downloads the five example frames (one per defect class) from a public copy of the
# Hu et al. (2024) FDM defect dataset. See sample_frames/SOURCE.txt for citation and terms.
set -e
cd "$(dirname "$0")/sample_frames"
BASE="https://huggingface.co/datasets/ppak10/Additive-Manufacturing-Benchmark/resolve/main/source/FDM-3D-Printing-Defect-Dataset/data"
curl -fL -o cracking.jpg     "$BASE/Cracking/Image_20231128200136974.jpg"
curl -fL -o layer_shift.jpg  "$BASE/Layer_shifting/Image_20231128160837016.jpg"
curl -fL -o off-platform.jpg "$BASE/Off_platform/Image_20231228113802865.jpg"
curl -fL -o stringing.jpg    "$BASE/Stringing/Image_20231228205049981.jpg"
curl -fL -o warping.jpg      "$BASE/Warping/Image_20231228115302905.jpg"
echo "Sample frames downloaded."
