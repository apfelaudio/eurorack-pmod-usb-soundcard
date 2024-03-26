FROM ubuntu:22.04

# Install build dependencies
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    jq \
    git

# Install oss-cad-suite
RUN curl -L $(curl -s "https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest" \
    | jq --raw-output '.assets[].browser_download_url' | grep "linux-x64") --output oss-cad-suite-linux-x64.tgz \
    && tar zxvf oss-cad-suite-linux-x64.tgz
ENV PATH="${PATH}:/oss-cad-suite/bin/"

# Update pip
RUN pip3 install --upgrade pip

# to compile OK --
# pip install .
# git submodule update --init --recursive
