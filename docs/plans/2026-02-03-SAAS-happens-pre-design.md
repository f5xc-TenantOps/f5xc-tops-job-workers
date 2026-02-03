# SAAS-happens-pre Helper Design

## Overview

Pre-deployment helper for the SAAS-happens lab that provisions F5 XC resources in the `f5-xc-lab-app-jqguisgi` tenant.

## Resources Created

| Resource | Name | Target |
|----------|------|--------|
| Origin Pool 1 | `{petname}-blue-pool` | `blue.f5demos.com:443` (TLS) |
| Origin Pool 2 | `{petname}-green-pool` | `green.f5demos.com:443` (TLS) |
| HTTP Load Balancer | `{petname}-routing-https-lb` | Routes to blue pool only |

### Load Balancer Configuration

- Domain: `{petname}.lab-app.f5demos.com`
- Certificate: `lab-app-wildcard` (from shared namespace)
- HTTPS with HTTP redirect and HSTS enabled
- Green pool is created but not attached (available for manual routing changes later)

## Execution Flow

1. Validate payload (requires `ssm_base_path` and `petname`)
2. Fetch tenant credentials from SSM Parameter Store
3. Create blue pool → wait for availability
4. Create green pool → wait for availability
5. Create load balancer (attached to blue pool only)
6. Return success response

## File Structure

```
udf_lab_helpers/
├── SAAS-happens-pre/
│   ├── function.py      # Lambda handler
│   └── requirements.txt # Dependencies
```

## Configuration

| Setting | Value |
|---------|-------|
| Tenant | `f5-xc-lab-app-jqguisgi` |
| Domain | `lab-app.f5demos.com` |
| Certificate | `lab-app-wildcard` |

## Dependencies

- `boto3`
- `f5xc_tops_py_client`
