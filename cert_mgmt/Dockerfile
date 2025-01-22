FROM public.ecr.aws/lambda/python:3.11

RUN yum install -y git \
 && yum clean all \
 && rm -rf /var/cache/yum

WORKDIR /var/task

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY function.py .

CMD ["function.lambda_handler"]

