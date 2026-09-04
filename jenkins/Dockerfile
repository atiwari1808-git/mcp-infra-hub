FROM jenkins/jenkins:lts

USER root

# Install prerequisites, Docker CLI, kubectl, and gcloud
RUN apt-get update && apt-get install -y \
      python3 python3-crcmod apt-transport-https ca-certificates gnupg curl lsb-release \
    && ln -sf /usr/bin/python3 /usr/bin/python

# Docker CLI (to build images via the mounted docker.sock)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y docker-ce-cli

# Google Cloud CLI + kubectl (via the gke-gcloud-auth-plugin)
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
    && apt-get update && apt-get install -y google-cloud-cli google-cloud-cli-gke-gcloud-auth-plugin kubectl

USER jenkins

