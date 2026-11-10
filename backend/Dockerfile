# Build stage
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /app

COPY pom.xml .
RUN mvn dependency:go-offline -B

COPY src ./src
RUN mvn package -DskipTests -B

# Runtime stage
FROM eclipse-temurin:17-jre AS runtime
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade apt libapt-pkg7.0 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system appgroup && useradd --system --gid appgroup appuser

COPY --from=builder /app/target/*.jar app.jar
RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app

EXPOSE 8080
ENV JAVA_OPTS="-XX:+UseContainerSupport -XX:+UseSerialGC -Xms64m -Xmx256m -XX:MaxMetaspaceSize=192m -XX:ReservedCodeCacheSize=48m -Xss512k -Djava.security.egd=file:/dev/./urandom"
USER appuser
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
