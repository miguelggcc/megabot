FROM python:3.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

ARG PUID=1000
ARG PGID=1000

RUN groupadd -g ${PGID} megabot && \
    useradd -u ${PUID} -g ${PGID} -m megabot

RUN apt-get -qq update \
    && apt-get -qq install -y --no-install-recommends \
        git g++ gcc autoconf automake \
        m4 libtool pkg-config make libcurl4-openssl-dev \
        libcrypto++-dev libsqlite3-dev libc-ares-dev \
        libsodium-dev libnautilus-extension-dev \
        libssl-dev libfreeimage-dev swig \
        && apt-get clean \
        && rm -rf /var/lib/apt/lists/*

# Installing mega sdk python binding
ENV MEGA_SDK_VERSION=3.12.2
RUN git clone https://github.com/meganz/sdk.git sdk && cd sdk \
    && git checkout v$MEGA_SDK_VERSION \
    && ./autogen.sh && ./configure --disable-silent-rules --enable-python --with-sodium --disable-examples CXXFLAGS="-std=c++17" \
    && make -j$(nproc --all) \
    && cd bindings/python/ && python3 setup.py bdist_wheel \
    && cd dist/ && pip3 install --no-cache-dir megasdk-$MEGA_SDK_VERSION-*.whl

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

USER megabot:megabot

WORKDIR /app

CMD ["python3", "./app/megabot.py"]