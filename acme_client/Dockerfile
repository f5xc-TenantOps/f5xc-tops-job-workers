FROM public.ecr.aws/lambda/python:3.11

RUN yum install -y epel-release && \
    yum install -y certbot python3-certbot-dns-route53 && \
    yum clean all

WORKDIR /var/task

COPY function.py ./
COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

CMD ["function.lambda_handler"]

