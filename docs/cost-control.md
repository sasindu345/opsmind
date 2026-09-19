# AWS Cost Control & Free-Tier Optimization Guide

OpsMind was engineered from the ground up to prevent surprise AWS cloud bills.

---

## 1. Architectural Cost-Saving Decisions

| Component | Traditional Setup Cost | OpsMind Architecture | Estimated Savings |
|---|---|---|---|
| **VPC NAT Gateway** | $32.40 / month ($0.045/hr + data) | **Zero NAT Gateway** (Single public subnet with Security Group) | **~$35.00 / month** |
| **Database** | RDS Postgres (~$15–$30/mo) | **DynamoDB `PAY_PER_REQUEST`** ($0 when idle, free tier covers 25 GB) | **~$20.00 / month** |
| **Compute** | Multiple ECS tasks / EKS cluster | **Single low-cost `t4g.small` or `t3.micro`** (Eligible for free tier) | **~$15.00 / month** |
| **Object Storage** | Unbounded S3 log growth | **30-Day Auto-Expiration Lifecycle Rule** | Prevents storage creep |
| **Log Groups** | Indefinite CloudWatch retention | **14-Day Log Retention Policy** | Prevents log storage fees |

---

## 2. Estimated Monthly Running Cost

- **Idle / Low Traffic (1,000 alerts/month)**: **$0.00 – $4.50 / month** (within AWS Free Tier limits).
- **Moderate Production (50,000 alerts/month)**: **$8.00 – $15.00 / month** (mainly EC2 compute and Bedrock tokens).

---

## 3. Best Practices for Free-Tier Users

1. **Use Gemini or Ollama locally for development**: Only use Amazon Bedrock for production deployments.
2. **Set up AWS Billing Alerts / AWS Budgets**: Create an AWS Budget at $10.00/month with email notifications.
3. **Use `terraform destroy` when done testing**: Tear down disposable demo environments in 2 minutes.
