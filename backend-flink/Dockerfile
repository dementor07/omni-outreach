FROM flink:1.18-scala_2.12

# Install Python and dependencies
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Install PyFlink
RUN ln -s /usr/bin/python3 /usr/bin/python && \
    pip3 install apache-flink==1.18.0 kafka-python-ng

# Add the orchestrator script
WORKDIR /opt/flink/usrlib
COPY orchestrator.py .
