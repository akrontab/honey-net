FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    cmake \
    check \
    cython3 \
    git \
    libcurl4-gnutls-dev \
    libev-dev \
    libglib2.0-dev \
    libnl-3-dev \
    libnl-route-3-dev \
    libssl-dev \
    libtool \
    libudns-dev \
    python3 \
    python3-dev \
    python3-pip \
    python3-yaml \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pymongo

WORKDIR /build
RUN git clone https://github.com/DinoTools/dionaea.git .

RUN cmake \
    -DCMAKE_INSTALL_PREFIX=/opt/dionaea \
    -DWITH_MODULE_EMU=OFF \
    -S . -B _build && \
    cmake --build _build -j$(nproc) && \
    cmake --install _build

EXPOSE 21 139 445

CMD ["/opt/dionaea/bin/dionaea"]
