// Example multistage pipeline for the platform's Jenkins provider.
// Configure repo credentials and the callback secret in Jenkins Credentials.
pipeline {
  agent { label 'python-allure' }

  options {
    timestamps()
    timeout(time: 180, unit: 'MINUTES')
    disableConcurrentBuilds()
  }

  parameters {
    string(name: 'REPOSITORY_URL', defaultValue: '', description: 'Repository URL without embedded credentials')
    string(name: 'REPOSITORY_ID', defaultValue: '', description: 'Optional repository identifier')
    string(name: 'BRANCH_NAME', defaultValue: 'main', description: 'Git branch')
    string(name: 'TEST_ENV', defaultValue: 'test', description: 'Test environment')
    string(name: 'PYTEST_ARGS', defaultValue: '-q', description: 'Options allowed by scripts/automation_run_tests.py')
    string(name: 'TEST_TAGS', defaultValue: '', description: 'pytest marker expression')
    string(name: 'TEST_SCOPE', defaultValue: '', description: 'Comma separated repository-relative test paths')
    string(name: 'BUILD_TIMEOUT_MINUTES', defaultValue: '120', description: 'Test execution timeout')
    string(name: 'AUTOMATION_EXECUTION_ID', defaultValue: '', description: 'Set by the test platform')
    string(name: 'AUTOMATION_PROJECT_ID', defaultValue: '', description: 'Set by the test platform')
    string(name: 'AUTOMATION_CALLBACK_KEY', defaultValue: '', description: 'Set by the test platform')
    string(name: 'AUTOMATION_CALLBACK_URL', defaultValue: '', description: 'Set by the test platform')
    string(name: 'AUTOMATION_HISTORY_URL', defaultValue: '', description: 'Set by the test platform')
    string(name: 'AUTOMATION_PROVIDER', defaultValue: 'JENKINS', description: 'Set by the test platform')
  }

  environment {
    // Replace with the exact public HTTPS origin of the test platform.
    AUTOMATION_CALLBACK_ORIGIN = 'https://test-platform.example.com'
    REPOSITORY_CREDENTIALS_ID = 'automation-codeup-readonly'
    CALLBACK_CREDENTIALS_ID = 'test-platform-automation-callback-secret'
  }

  stages {
    stage('Validate inputs and checkout') {
      steps {
        script {
          def branch = params.BRANCH_NAME.trim()
          if (!branch.matches('^[A-Za-z0-9._/-]{1,200}$') || branch.startsWith('-') || branch.contains('..') || branch.contains('//') || branch.contains('@{')) {
            error('Invalid Git branch name')
          }
          def repo = params.REPOSITORY_URL.trim()
          if (repo.contains('\n') || repo.contains('\r') || !(repo.startsWith('https://codeup.aliyun.com/') || repo.startsWith('ssh://git@codeup.aliyun.com/')) || repo.contains('@') && repo.startsWith('https://')) {
            error('Repository URL is outside the configured Codeup allowlist or contains credentials')
          }
          if (!params.TEST_ENV.matches('^[A-Za-z0-9_.-]{0,100}$') || [params.PYTEST_ARGS, params.TEST_TAGS, params.TEST_SCOPE].any { it.contains('\n') || it.contains('\r') }) {
            error('Test parameters contain unsupported characters')
          }
          if (!params.AUTOMATION_EXECUTION_ID.isInteger() || !params.AUTOMATION_PROJECT_ID.isInteger()) {
            error('This example is intended to be triggered by the test platform')
          }
          env.AUTOMATION_START_MS = System.currentTimeMillis().toString()
        }
        checkout([
          $class: 'GitSCM',
          branches: [[name: "${params.BRANCH_NAME}"]],
          userRemoteConfigs: [[url: "${params.REPOSITORY_URL}", credentialsId: env.REPOSITORY_CREDENTIALS_ID]],
          extensions: [[$class: 'CleanBeforeCheckout']]
        ])
      }
    }

    stage('Install dependencies') {
      steps {
        sh 'python3 -m venv .venv'
        sh '.venv/bin/pip install --disable-pip-version-check -r requirements.txt'
      }
    }

    stage('Inherit Allure history') {
      steps {
        script {
          try {
            withCredentials([string(credentialsId: env.CALLBACK_CREDENTIALS_ID, variable: 'AUTOMATION_CALLBACK_SECRET')]) {
              sh 'python3 scripts/automation_callback.py history'
            }
          } catch (err) {
            echo "Could not inherit prior Allure history; continuing with this run (${err.getClass().getSimpleName()})."
          }
        }
      }
    }

    stage('Run pytest') {
      steps {
        script {
          def minutes = params.BUILD_TIMEOUT_MINUTES.isInteger() ? params.BUILD_TIMEOUT_MINUTES.toInteger() : 120
          if (minutes < 1 || minutes > 180) {
            error('BUILD_TIMEOUT_MINUTES must be between 1 and 180')
          }
          timeout(time: minutes, unit: 'MINUTES') {
            withEnv([
              "TEST_ENV=${params.TEST_ENV}",
              "PYTEST_ARGS=${params.PYTEST_ARGS}",
              "TEST_TAGS=${params.TEST_TAGS}",
              "TEST_SCOPE=${params.TEST_SCOPE}"
            ]) {
              def result = sh(returnStatus: true, script: '.venv/bin/python scripts/automation_run_tests.py')
              if (result != 0) {
                error("pytest failed with exit code ${result}")
              }
            }
          }
        }
      }
    }

    stage('Generate Allure report') {
      steps {
        script {
          if (fileExists('allure-results')) {
            def result = sh(returnStatus: true, script: 'allure generate allure-results --clean -o allure-report')
            if (result != 0) {
              echo "Allure report generation failed with exit code ${result}. Callback will still upload results and logs."
              currentBuild.result = 'FAILURE'
            }
          } else {
            echo 'No allure-results directory was produced.'
            currentBuild.result = 'FAILURE'
          }
        }
      }
    }
  }

  post {
    always {
      script {
        sh 'if [ -d allure-report ]; then (cd allure-report && zip -qr ../allure-report.zip .); fi'
        sh 'if [ -d allure-results ]; then zip -qr allure-results.zip allure-results; fi'
        archiveArtifacts artifacts: 'allure-report.zip,allure-results.zip,run.log', allowEmptyArchive: true
        env.AUTOMATION_STATUS = currentBuild.currentResult ?: 'FAILURE'
        if (params.AUTOMATION_CALLBACK_URL?.trim()) {
          withCredentials([string(credentialsId: env.CALLBACK_CREDENTIALS_ID, variable: 'AUTOMATION_CALLBACK_SECRET')]) {
            def uploadResult = sh(returnStatus: true, script: 'python3 scripts/automation_callback.py upload')
            if (uploadResult != 0) {
              echo "ERROR: test platform callback failed (exit code ${uploadResult}); report and result archives remain in Jenkins artifacts."
              if (currentBuild.currentResult == 'SUCCESS') {
                currentBuild.result = 'UNSTABLE'
              }
            }
          }
        } else {
          echo 'ERROR: platform callback URL is missing; report upload was skipped.'
          if (currentBuild.currentResult == 'SUCCESS') {
            currentBuild.result = 'UNSTABLE'
          }
        }
      }
    }
  }
}
