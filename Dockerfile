FROM fedora:25
MAINTAINER Red Hat, Inc. <container-tools@redhat.com>

# Install required dependencies and commissaire services
RUN dnf -y update && \
dnf -y install --setopt=tsflags=nodocs openssh-clients redhat-rpm-config python3-pip python3-virtualenv git gcc libffi-devel openssl-devel && \
git clone https://github.com/projectatomic/commissaire-service.git && \
virtualenv-3 /environment && \
. /environment/bin/activate && \
cd commissaire-service && \
pip install -U pip && \
pip install -r requirements.txt && \
pip install . && \
cd .. && \
pip freeze > /installed-python-deps.txt && \
dnf remove -y gcc git redhat-rpm-config libffi-devel && \
dnf clean all

# Copy the all-in-one start script
COPY tools/startup-services.sh /commissaire/

# Configuration directory. Use --volume=/path/to/your/configs:/etc/commissaire
VOLUME /etc/commissaire/

# Run everything from /commissaire
WORKDIR /commissaire
# Execute the all-in-one-script
CMD /commissaire/startup-services.sh
