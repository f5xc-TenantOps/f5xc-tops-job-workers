# Step Function Workflow Definitions

## provisioning-workflow.json

The main provisioning workflow that creates namespaces, users, and resources based on job configuration.

### Variable Substitution

Before deploying, replace these placeholders with actual Lambda ARNs:

| Placeholder | Lambda |
|-------------|--------|
| `${FetchJobConfigLambdaArn}` | fetch_job_config |
| `${NsCreateLambdaArn}` | ns_create |
| `${UserCreateLambdaArn}` | user_create |
| `${ResourceOrchestratorLambdaArn}` | resource_orchestrator |

### ARN Substitution

Before deploying, substitute the placeholder ARNs with actual values.

**Option 1: Using environment variables and envsubst**

```bash
export FetchJobConfigLambdaArn="arn:aws:lambda:us-east-1:ACCOUNT:function:tops-fetch-job-config"
export NsCreateLambdaArn="arn:aws:lambda:us-east-1:ACCOUNT:function:tops-ns-create"
export UserCreateLambdaArn="arn:aws:lambda:us-east-1:ACCOUNT:function:tops-user-create"
export ResourceOrchestratorLambdaArn="arn:aws:lambda:us-east-1:ACCOUNT:function:tops-resource-orchestrator"

envsubst < provisioning-workflow.json > provisioning-workflow-deployed.json
```

**Option 2: Using sed**

```bash
sed -e 's|\${FetchJobConfigLambdaArn}|arn:aws:lambda:us-east-1:ACCOUNT:function:tops-fetch-job-config|g' \
    -e 's|\${NsCreateLambdaArn}|arn:aws:lambda:us-east-1:ACCOUNT:function:tops-ns-create|g' \
    -e 's|\${UserCreateLambdaArn}|arn:aws:lambda:us-east-1:ACCOUNT:function:tops-user-create|g' \
    -e 's|\${ResourceOrchestratorLambdaArn}|arn:aws:lambda:us-east-1:ACCOUNT:function:tops-resource-orchestrator|g' \
    provisioning-workflow.json > provisioning-workflow-deployed.json
```

### Deployment

```bash
# Deploy the substituted workflow
aws stepfunctions create-state-machine \
  --name tops-provisioning-workflow \
  --definition file://provisioning-workflow-deployed.json \
  --role-arn arn:aws:iam::ACCOUNT:role/tops-step-function-role
```

### Complete Deployment Workflow

```bash
# 1. Set environment variables with actual Lambda ARNs
export FetchJobConfigLambdaArn="arn:aws:lambda:us-east-1:123456789012:function:tops-fetch-job-config"
export NsCreateLambdaArn="arn:aws:lambda:us-east-1:123456789012:function:tops-ns-create"
export UserCreateLambdaArn="arn:aws:lambda:us-east-1:123456789012:function:tops-user-create"
export ResourceOrchestratorLambdaArn="arn:aws:lambda:us-east-1:123456789012:function:tops-resource-orchestrator"

# 2. Substitute placeholders
envsubst < provisioning-workflow.json > provisioning-workflow-deployed.json

# 3. Create or update the state machine
aws stepfunctions create-state-machine \
  --name tops-provisioning-workflow \
  --definition file://provisioning-workflow-deployed.json \
  --role-arn arn:aws:iam::123456789012:role/tops-step-function-role

# Or update an existing state machine
aws stepfunctions update-state-machine \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:tops-provisioning-workflow \
  --definition file://provisioning-workflow-deployed.json
```

### Testing

Start an execution with:

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:REGION:ACCOUNT:stateMachine:tops-provisioning-workflow \
  --input '{"job_id": "test-job", "email": "test@example.com", "petname": "test-pet"}'
```
