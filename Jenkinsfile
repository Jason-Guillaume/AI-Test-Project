// Example multistage pipeline for the platform's Jenkins provider.
// Configure repo credentials and the callback secret in Jenkins Credentials.
def markAutomationInterruption(interrupted, String stageName) {
  def timedOut = interrupted.causes.any { cause ->
    cause.class.name.contains('ExceededTimeout') || cause.toString().toLowerCase().contains('timeout')
  }
  env.AUTOMATION_STATUS = timedOut ? 'TIMEOUT' : 'CANCELLED'
  currentBuild.result = timedOut ? 'FAILURE' : 'ABORTED'
  echo timedOut ? "${stageName} timed out; post actions will upload available results and logs." : "${stageName} was cancelled; post actions will upload available results and logs."
}

pipeline {
  agent { label 'python-allure' }

  options {
    timestamps()
    // 测试步骤最多 180 分钟；全流水线限时还覆盖依赖安装、报告和有界回调。
    timeout(time: 300, unit: 'MINUTES')
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
          try {
            timeout(time: 15, unit: 'MINUTES') {
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
              checkout([
                $class: 'GitSCM',
                branches: [[name: "${params.BRANCH_NAME}"]],
                userRemoteConfigs: [[url: "${params.REPOSITORY_URL}", credentialsId: env.REPOSITORY_CREDENTIALS_ID]],
                extensions: [[$class: 'CleanBeforeCheckout']]
              ])
            }
          } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException interrupted) {
            markAutomationInterruption(interrupted, 'Checkout')
            throw interrupted
          }
        }
      }
    }

    stage('Install dependencies') {
      steps {
        script {
          try {
            timeout(time: 45, unit: 'MINUTES') {
              sh 'python3 -m venv .venv'
              sh '.venv/bin/pip install --disable-pip-version-check -r requirements.txt'
            }
          } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException interrupted) {
            markAutomationInterruption(interrupted, 'Dependency installation')
            throw interrupted
          }
        }
      }
    }

    stage('Inherit Allure history') {
      steps {
        script {
          try {
            timeout(time: 3, unit: 'MINUTES') {
              withCredentials([string(credentialsId: env.CALLBACK_CREDENTIALS_ID, variable: 'AUTOMATION_CALLBACK_SECRET')]) {
                sh 'python3 scripts/automation_callback.py history'
              }
            }
          } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException interrupted) {
            markAutomationInterruption(interrupted, 'Allure history retrieval')
            throw interrupted
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
          try {
            timeout(time: minutes, unit: 'MINUTES') {
              withEnv([
                "TEST_ENV=${params.TEST_ENV}",
                "PYTEST_ARGS=${params.PYTEST_ARGS}",
                "TEST_TAGS=${params.TEST_TAGS}",
                "TEST_SCOPE=${params.TEST_SCOPE}"
              ]) {
                def result = sh(returnStatus: true, script: '.venv/bin/python scripts/automation_run_tests.py')
                env.AUTOMATION_STATUS = result == 0 ? 'SUCCESS' : 'FAILED'
                if (result != 0) {
                  currentBuild.result = 'FAILURE'
                  echo "pytest exited with code ${result}; continuing to collect Allure results and logs."
                }
              }
            }
          } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException interrupted) {
            markAutomationInterruption(interrupted, 'Test execution')
            throw interrupted
          }
        }
      }
    }
  }

  post {
    always {
      script {
        if (!env.AUTOMATION_STATUS?.trim()) {
          env.AUTOMATION_STATUS = currentBuild.currentResult == 'SUCCESS' ? 'SUCCESS' : 'FAILED'
        }
        if (fileExists('allure-results')) {
          def reportResult = -1
          try {
            timeout(time: 15, unit: 'MINUTES') {
              reportResult = sh(returnStatus: true, script: 'allure generate allure-results --clean -o allure-report')
            }
          } catch (err) {
            echo "Allure HTML generation did not finish (${err.getClass().getSimpleName()}); results and logs will still be uploaded."
          }
          if (reportResult != 0) {
            echo "Allure HTML generation failed with exit code ${reportResult}; results and logs will still be uploaded."
          }
          if (reportResult != 0 || !fileExists('allure-report/index.html')) {
            if (env.AUTOMATION_STATUS != 'CANCELLED' && env.AUTOMATION_STATUS != 'TIMEOUT') {
              env.AUTOMATION_STATUS = 'FAILED'
              currentBuild.result = 'FAILURE'
            }
          }
        } else {
          echo 'No allure-results directory was produced; uploading logs and execution metadata.'
          if (env.AUTOMATION_STATUS == 'SUCCESS') {
            env.AUTOMATION_STATUS = 'FAILED'
            currentBuild.result = 'FAILURE'
          }
        }
        env.JENKINS_RESULT = currentBuild.currentResult ?: 'FAILURE'
        if (!fileExists('run.log')) {
          try {
            writeFile file: 'run.log', text: 'pytest was not started or produced no output.\n'
          } catch (err) {
            echo "Could not create the fallback run.log (${err.getClass().getSimpleName()}); callback will still run."
          }
        }
        try {
          timeout(time: 5, unit: 'MINUTES') {
            sh(returnStatus: true, script: 'if [ -f allure-report/index.html ]; then (cd allure-report && zip -qr ../allure-report.zip .); else rm -f allure-report.zip; fi')
            sh(returnStatus: true, script: 'if [ -d allure-results ]; then zip -qr allure-results.zip allure-results; fi')
          }
        } catch (err) {
          echo "Artifact packaging did not finish (${err.getClass().getSimpleName()}); callback will still run."
        }
        try {
          archiveArtifacts artifacts: 'allure-report.zip,allure-results.zip,run.log', allowEmptyArchive: true
        } catch (err) {
          echo "Could not archive one or more artifacts (${err.getClass().getSimpleName()}); callback will still run."
        }
        if (params.AUTOMATION_CALLBACK_URL?.trim()) {
          try {
            timeout(time: 90, unit: 'SECONDS') {
              withCredentials([string(credentialsId: env.CALLBACK_CREDENTIALS_ID, variable: 'AUTOMATION_CALLBACK_SECRET')]) {
                def uploadResult = sh(returnStatus: true, script: 'python3 scripts/automation_callback.py upload')
                if (uploadResult != 0) {
                  echo "ERROR: callback failed after bounded retries (exit code ${uploadResult}); inspect this Jenkins build and retry delivery after restoring platform connectivity."
                }
              }
            }
          } catch (err) {
            echo "ERROR: callback could not complete (${err.getClass().getSimpleName()}); inspect this Jenkins build and retry delivery after restoring platform connectivity."
          }
        } else {
          echo 'ERROR: platform callback URL is missing; report upload was skipped.'
        }
      }
    }
  }
}
