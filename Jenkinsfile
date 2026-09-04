pipeline {
    agent any
    environment {
        PROJECT_ID = 'mcp-infra-hub'
        REGION     = 'us-central1'
        REPO       = "us-central1-docker.pkg.dev/mcp-infra-hub/infra-hub"
        IMAGE      = "mcp-server"
        CLUSTER    = 'infra-hub-test'
        ZONE       = 'us-central1-a'
    }
    stages {
        stage('Checkout') { steps { checkout scm } }

        stage('Setup GCP') {
            steps {
                sh '''
                    gcloud config set project $PROJECT_ID
                    gcloud auth configure-docker $REGION-docker.pkg.dev --quiet
                '''
            }
        }
        stage('Build')  { steps { sh 'docker build -t $REPO/$IMAGE:$BUILD_NUMBER ./server' } }
        stage('Push')   { steps { sh 'docker push $REPO/$IMAGE:$BUILD_NUMBER' } }

        stage('Deploy to GKE') {
            steps {
                sh '''
                    gcloud container clusters get-credentials $CLUSTER --zone $ZONE
                    kubectl set image deployment/mcp-server \
                      mcp-server=$REPO/$IMAGE:$BUILD_NUMBER -n infra-hub
                    kubectl rollout status deployment/mcp-server -n infra-hub
                '''
            }
        }
    }
}

