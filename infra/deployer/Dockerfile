# The deployer (MAG-308): Terraform, the AWS CLI, uv, git and the Docker
# client in one image, so bringing dev up on AWS needs only Git and Docker
# Desktop on the computer. compose.aws.yml runs it with the folder of the
# clones in /work, ~/.aws and the Docker socket of the computer: the images dev_up.py builds are built by the
# computer's Docker, the state stays in envs/dev and the Power BI profile
# lands in the computer's ~/.aws. Steps: README, "From zero to AWS".
# The same base as SecurePay's image: Python 3.12 with uv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG TERRAFORM_VERSION=1.13.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gnupg unzip \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o /tmp/terraform.zip \
    && unzip -q /tmp/terraform.zip -d /usr/local/bin \
    && curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscli.zip \
    && unzip -q /tmp/awscli.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/terraform.zip /tmp/awscli.zip /tmp/aws

# The clones belong to the computer's user, not to root, and on Windows
# they are checked out with CRLF: without these, git would refuse them or
# see every file as changed, and dev_up.py would tag the images "dirty".
RUN git config --system --add safe.directory '*' \
    && git config --system core.autocrlf true

# Caches in a named volume: Terraform's providers (TF_DATA_DIR keeps the
# Linux providers apart from a Windows `terraform init` in envs/dev), uv's
# downloads and securepay-csv's environment.
ENV TF_DATA_DIR=/cache/terraform \
    TF_PLUGIN_CACHE_DIR=/cache/terraform-plugins \
    TF_IN_AUTOMATION= \
    UV_CACHE_DIR=/cache/uv \
    UV_LINK_MODE=copy \
    CHECKPOINT_DISABLE=1

COPY deploy.sh /usr/local/bin/deploy
# A Windows checkout may have turned the script's line endings into CRLF.
RUN sed -i 's/\r$//' /usr/local/bin/deploy && chmod +x /usr/local/bin/deploy

ENTRYPOINT ["deploy"]
CMD ["help"]
