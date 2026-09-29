# Judge0 1.13.1 + judge0/judge0#599 (cgroup v2 / isolate v2), built from reviewed,
# pinned sources. See docs/JUDGE0_CGROUP_V2.md for the review and the test evidence.
#
# The Judge0 application is the PR commit unchanged. The base deviates from
# judge0/compilers#29: only Python 3.8.1 (the runtime HireAiPro grades), built
# natively (arm64/amd64), instead of the full 30-language toolchain image.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git pkg-config ca-certificates curl xz-utils cron sudo libpq-dev procps \
      libcap-dev libseccomp-dev libsystemd-dev \
      zlib1g-dev libssl-dev libffi-dev libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev \
 && rm -rf /var/lib/apt/lists/*

# isolate — pinned to the reviewed ioi/isolate v2.6 commit (PR #29 clones unpinned master).
ARG ISOLATE_TAG=v2.6
ARG ISOLATE_SHA=19ec4bd3fac386ae4cb95a7d43d8188710154661
RUN git clone --depth 1 --branch ${ISOLATE_TAG} https://github.com/ioi/isolate.git /tmp/isolate && cd /tmp/isolate \
 && test "$(git rev-parse HEAD)" = "${ISOLATE_SHA}" \
 && make -j"$(nproc)" isolate isolate-check-environment \
 && install -m 4755 isolate /usr/local/bin/isolate \
 && install -m 0755 isolate-check-environment /usr/local/bin/isolate-check-environment \
 && printf 'box_root = /var/local/lib/isolate\nlock_root = /run/isolate/locks\ncg_root = /sys/fs/cgroup/isolate\nsubid_user = isolate\n' > /usr/local/etc/isolate \
 && useradd --system --no-create-home isolate && echo 'isolate:60000:1000' > /etc/subuid && echo 'isolate:60000:1000' > /etc/subgid \
 && mkdir -p /var/local/lib/isolate /run/isolate/locks && rm -rf /tmp/isolate
ENV BOX_ROOT=/var/local/lib/isolate

# Ruby 2.7.8 (Judge0 1.13 needs Ruby 2.7) against OpenSSL 1.1.1w — Ruby 2.7 cannot
# build against bookworm's OpenSSL 3. Both are EOL upstream (as in Judge0 1.13's own
# base image); they serve the localhost-only API, not the sandbox boundary.
ARG OPENSSL_SHA256=cf3098950cb4d853ad95c0841f1f9c6d3dc102dccfcacd521d93925208b76ac8
ARG RUBY_SHA256=c2dab63cbc8f2a05526108ad419efa63a67ed4074dbbcf9fc2b1ca664cb45ba0
RUN curl -fsSL https://github.com/openssl/openssl/releases/download/OpenSSL_1_1_1w/openssl-1.1.1w.tar.gz -o /tmp/ossl.tgz \
 && echo "${OPENSSL_SHA256}  /tmp/ossl.tgz" | sha256sum -c - \
 && mkdir /tmp/ossl && tar -xzf /tmp/ossl.tgz -C /tmp/ossl --strip-components=1 && cd /tmp/ossl \
 && ./config --prefix=/opt/openssl-1.1 --openssldir=/opt/openssl-1.1 shared no-tests >/dev/null && make -j"$(nproc)" >/dev/null && make install_sw >/dev/null \
 && curl -fsSL https://cache.ruby-lang.org/pub/ruby/2.7/ruby-2.7.8.tar.gz -o /tmp/ruby.tgz \
 && echo "${RUBY_SHA256}  /tmp/ruby.tgz" | sha256sum -c - \
 && mkdir /tmp/ruby && tar -xzf /tmp/ruby.tgz -C /tmp/ruby --strip-components=1 && cd /tmp/ruby \
 && ./configure --prefix=/usr/local/ruby-2.7 --with-openssl-dir=/opt/openssl-1.1 --disable-install-doc LDFLAGS="-Wl,-rpath,/opt/openssl-1.1/lib" >/dev/null \
 && make -j"$(nproc)" >/dev/null && make install >/dev/null && rm -rf /tmp/ossl* /tmp/ruby*
ENV PATH="/usr/local/ruby-2.7/bin:$PATH"

# Python 3.8.1 at the path db/languages/active.rb uses. Tarball GPG-verified
# (Łukasz Langa, E3FF2839C048B25C084DEBE9B26995E310250568); sha256 pinned here.
ARG PY_SHA256=75894117f6db7051c1b34f37410168844bbb357c139a8a10a352e9bf8be594e8
RUN curl -fsSL https://www.python.org/ftp/python/3.8.1/Python-3.8.1.tar.xz -o /tmp/py.tar.xz \
 && echo "${PY_SHA256}  /tmp/py.tar.xz" | sha256sum -c - \
 && mkdir /tmp/py && tar -xf /tmp/py.tar.xz -C /tmp/py --strip-components=1 && cd /tmp/py \
 && ./configure --prefix=/usr/local/python-3.8.1 --with-openssl=/opt/openssl-1.1 LDFLAGS="-Wl,-rpath,/opt/openssl-1.1/lib" >/dev/null && make -j"$(nproc)" >/dev/null && make install >/dev/null \
 && rm -rf /tmp/py /tmp/py.tar.xz

# Judge0 application: judge0/judge0#599 head, reviewed diff vs merge base = 2 files, +34/-4.
ARG JUDGE0_SHA=6cf7851c7b161d6dae0213e26e79d6fdcce7453d
RUN git clone https://github.com/judge0/judge0.git /api && cd /api  && git fetch -q origin pull/599/head && git checkout -q "${JUDGE0_SHA}"  && test "$(git rev-parse HEAD)" = "${JUDGE0_SHA}" && rm -rf .git \
 && rm judge0.conf  # sample config; sourced with allexport it would override the container env (hosts, passwords)

EXPOSE 2358
WORKDIR /api
RUN echo "gem: --no-document" > /root/.gemrc && gem install bundler:2.1.4 && RAILS_ENV=production bundle
RUN cp /api/cron/* /etc/cron.d/ && cat /etc/cron.d/* | crontab -
ENTRYPOINT ["/api/docker-entrypoint.sh"]
CMD ["/api/scripts/server"]
RUN useradd -u 1000 -m -r judge0 && echo "judge0 ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers && chown judge0: /api/tmp/
USER judge0
ENV JUDGE0_VERSION="1.13.1-cgv2-pr599"
