// Proxmox API Simulator — CI/CD: multi-arch push (Harbor + Docker Hub) + deploy
//
// Один файл: Build (DinD) → Deploy (kubectl set image в релиз simulators).
// Первый install lab — через DevOpsTools/K3S: make addon-simulators
// (Ingress https://proxmox.devops.org.ru уже из addon values).
//
// Версия образа = VERSION из коммита. Локальный bump: make bump-patch / make push.
// Теги: :{VERSION} и :latest (без sha).
//
// Credentials (Global):
//   harbor-devops-tools-push-pull-access — Harbor devops-tools (robot)
//   docker-hub                          — Docker Hub (inecs)
//   k3s-kubeconfig                      — kubeconfig к K3S
//   ssh-gitea-key                       — SCM checkout Gitea (в job)

pipeline {
    agent none

    options {
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
        timeout(time: 60, unit: 'MINUTES')
        timestamps()
    }

    environment {
        HARBOR_REGISTRY     = 'hub.antropoff.ru'
        HARBOR_IMAGE        = 'hub.antropoff.ru/devops-tools/proxmox-api-simulator'
        DOCKERHUB_IMAGE     = 'inecs/proxmox-api-simulator'
        BUILDX_BUILDER      = "jenkins-proxmox-api-simulator-${env.BUILD_NUMBER}"
        HELM_NAMESPACE      = 'simulators'
        DEPLOYMENT_NAME     = 'simulators-proxmox'
        INGRESS_HOST        = 'proxmox.devops.org.ru'
        TZ                  = 'Europe/Moscow'
    }

    stages {
        stage('Build & push') {
            when {
                anyOf {
                    branch 'main'
                    branch 'master'
                }
            }
            agent { label 'docker' }
            stages {
                stage('Checkout') {
                    steps {
                        checkout scm
                    }
                }

                stage('Version') {
                    steps {
                        script {
                            env.IMAGE_VERSION = readFile('VERSION').trim()
                            if (!env.IMAGE_VERSION) {
                                error('VERSION file is empty')
                            }
                            echo "IMAGE_VERSION from VERSION → ${env.IMAGE_VERSION}"
                        }
                    }
                }

                stage('Buildx push') {
                    steps {
                        withCredentials([
                            usernamePassword(
                                credentialsId: 'harbor-devops-tools-push-pull-access',
                                usernameVariable: 'HARBOR_USER',
                                passwordVariable: 'HARBOR_PASS'
                            ),
                            usernamePassword(
                                credentialsId: 'docker-hub',
                                usernameVariable: 'DOCKERHUB_USER',
                                passwordVariable: 'DOCKERHUB_PASS'
                            )
                        ]) {
                            container('docker') {
                                sh '''
                                    set -eux

                                    test -n "${IMAGE_VERSION}"
                                    echo "Building tags: ${IMAGE_VERSION}, latest (amd64+arm64)"

                                    echo "$HARBOR_PASS" | docker login "$HARBOR_REGISTRY" -u "$HARBOR_USER" --password-stdin
                                    echo "$DOCKERHUB_PASS" | docker login -u "$DOCKERHUB_USER" --password-stdin

                                    docker buildx rm "$BUILDX_BUILDER" 2>/dev/null || true
                                    docker buildx create --name "$BUILDX_BUILDER" --driver docker-container --use
                                    docker buildx inspect --bootstrap >/dev/null

                                    docker buildx build \
                                      --platform linux/amd64,linux/arm64 \
                                      --target runtime \
                                      --build-arg "APP_VERSION=${IMAGE_VERSION}" \
                                      --provenance=false --sbom=false --push \
                                      -t "${HARBOR_IMAGE}:${IMAGE_VERSION}" \
                                      -t "${HARBOR_IMAGE}:latest" \
                                      -t "${DOCKERHUB_IMAGE}:${IMAGE_VERSION}" \
                                      -t "${DOCKERHUB_IMAGE}:latest" \
                                      -f Dockerfile .

                                    echo "--- Harbor ---"
                                    docker buildx imagetools inspect "${HARBOR_IMAGE}:${IMAGE_VERSION}" | sed -n '1,40p'
                                    echo "--- Docker Hub ---"
                                    docker buildx imagetools inspect "${DOCKERHUB_IMAGE}:${IMAGE_VERSION}" | sed -n '1,40p'

                                    docker buildx rm "$BUILDX_BUILDER" || true
                                '''
                            }
                        }
                    }
                }

                stage('Deploy') {
                    steps {
                        withCredentials([
                            file(credentialsId: 'k3s-kubeconfig', variable: 'KUBECONFIG')
                        ]) {
                            container('docker') {
                                sh '''
                                    set -eux

                                    if ! command -v kubectl >/dev/null 2>&1; then
                                      apk add --no-cache curl >/dev/null
                                      ARCH="$(uname -m)"
                                      case "$ARCH" in
                                        x86_64) ARCH=amd64 ;;
                                        aarch64|arm64) ARCH=arm64 ;;
                                      esac
                                      KVER="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
                                      curl -fsSLo /usr/local/bin/kubectl \
                                        "https://dl.k8s.io/release/${KVER}/bin/linux/${ARCH}/kubectl"
                                      chmod +x /usr/local/bin/kubectl
                                    fi

                                    kubectl version --client || true

                                    if ! kubectl -n "$HELM_NAMESPACE" get deploy "$DEPLOYMENT_NAME" >/dev/null 2>&1; then
                                      echo "Deployment ${HELM_NAMESPACE}/${DEPLOYMENT_NAME} not found." >&2
                                      echo "Сначала: make addon-simulators (Ingress ${INGRESS_HOST})." >&2
                                      exit 1
                                    fi

                                    echo "Rolling ${DOCKERHUB_IMAGE}:${IMAGE_VERSION} → ${HELM_NAMESPACE}/${DEPLOYMENT_NAME}"
                                    echo "Public URL: https://${INGRESS_HOST}/"

                                    # One set-image avoids double ReplicaSet churn; migrate when present.
                                    SET_ARGS=("simulator=${DOCKERHUB_IMAGE}:${IMAGE_VERSION}")
                                    if kubectl -n "$HELM_NAMESPACE" get deploy "$DEPLOYMENT_NAME" \
                                         -o jsonpath='{.spec.template.spec.initContainers[*].name}' \
                                         | tr ' ' '\n' | grep -qx migrate; then
                                      SET_ARGS+=("migrate=${DOCKERHUB_IMAGE}:${IMAGE_VERSION}")
                                    fi
                                    kubectl -n "$HELM_NAMESPACE" set image \
                                      "deployment/${DEPLOYMENT_NAME}" "${SET_ARGS[@]}"

                                    kubectl -n "$HELM_NAMESPACE" rollout status \
                                      "deployment/${DEPLOYMENT_NAME}" --timeout=1200s
                                    kubectl -n "$HELM_NAMESPACE" get deploy,po,ing -o wide
                                '''
                            }
                        }
                    }
                }
            }
            post {
                always {
                    script {
                        try {
                            container('docker') {
                                sh 'docker buildx rm "$BUILDX_BUILDER" 2>/dev/null || true'
                            }
                        } catch (Ignored) {
                            // pod may already be gone
                        }
                    }
                }
                success {
                    echo "✓ ${DOCKERHUB_IMAGE}:{${IMAGE_VERSION},latest} → https://${INGRESS_HOST}/"
                }
                failure {
                    echo "✗ Build/push/deploy failed — см. лог"
                }
            }
        }
    }

    post {
        success {
            echo "✓ Version: ${IMAGE_VERSION}"
            echo "✓ Harbor:  ${HARBOR_IMAGE}:{${IMAGE_VERSION},latest}"
            echo "✓ Hub:     ${DOCKERHUB_IMAGE}:{${IMAGE_VERSION},latest}"
            echo "✓ Live:    https://${INGRESS_HOST}/"
        }
        failure {
            echo "✗ Pipeline failed"
        }
    }
}
