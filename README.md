# f5xc-tops-job-workers
These lambdas are used for tenantOps jobs.

## Build Workflow
The lambdas are built via Github Action then pushed to an S3 bucket based on branch.
They are deployed to AWS by the [tops-infrastucture] repository.

## General Workers
These are generalized workers used across all use cases (Sale tenant operations, UDF labs, etc.)

### [Acme Client](./acme_client/)
**Purpose:** Create a wildcard cert using a DNS challenge, check cert expiry, on creation/renewal write cert to S3.

**Trigger:** Periodic.

### [Cert Management](./cert_mgmt/)
**Purpose:** Write certificate to an XC tenant.

**Trigger:** on S3 bucket file creation/update.

### [Token Refresh](./token_refresh/)
**Purpose:** Update the expiry of an XC API token or service credential.

**Trigger:** Periodic.

### [Namespace Create](./ns_create)
**Purpose:** Create an XC namespace.

**Trigger:** Invoked by another lambda.

### [Namespace Remove](./ns_remove)
**Purpose:** Cascade delete an XC namespace (thus removing all resources in the namespace).

**Trigger:** Invoked by another lambda.

### [User Create](./user_create/)
**Purpose:** Create an XC user with a defined set of permissions.

**Trigger:** Invoked by another lambda.

### [User Remove](./user_remove/)
**Purpose:** Delete an XC user. 

**Trigger:** Invoked by another lambda.

## UDF
These lambdas are used to trigger and clean UDF lab deployments.

### [UDF Dispatch](./udf_dispatch/)
**Purpose:** Pull SQS message from shared queue, write an entry to the DynamoDB state table.

**Trigger:** SQS message recieved.

### [UDF Worker](./udf_worker/)
**Purpose:** Main business logic for UDF deployments. On record creation, deploy an NS, user, and execute a pre-deployment lambda (if applicable). On record deletion, remove user, NS, and execute a post-deployment lambda (if applicable).

**Trigger:** DynamoDB stream

### [UDF Helpers](./udf_helpers/)
**Purpose:** Lab resource (Loadbalancers, Origin pools, etc.) deployment and cleanup.

**Trigger:** Invoked by *UDF Worker*.



