FROM flink:1.18-scala_2.12

# Python + build deps. PyFlink needs the python3-dev headers to compile the
# native bridge bits. wget is used to download connector JARs.
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev wget && \
    rm -rf /var/lib/apt/lists/*

# Connector JARs — Kafka (for both DataStream and SQL) + Redis for the
# Dragonfly analytics sink. The Bahir Redis connector is the one Flink SQL's
# 'connector' = 'redis' resolves to.
RUN wget -q -P /opt/flink/lib \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.1.0-1.18/flink-sql-connector-kafka-3.1.0-1.18.jar && \
    wget -q -P /opt/flink/lib \
    https://repo1.maven.org/maven2/org/apache/bahir/flink-connector-redis_2.12/1.1.0/flink-connector-redis_2.12-1.1.0.jar

# PyFlink runtime.
RUN ln -s /usr/bin/python3 /usr/bin/python && \
    pip3 install --no-cache-dir apache-flink==1.18.0 kafka-python-ng

# Orchestrator + analytics SQL.
WORKDIR /opt/flink/usrlib
COPY orchestrator.py analytics.sql ./
