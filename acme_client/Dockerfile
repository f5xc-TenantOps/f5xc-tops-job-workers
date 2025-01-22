FROM public.ecr.aws/lambda/python:3.11

WORKDIR /var/task

COPY function.py ./
COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

CMD ["function.lambda_handler"]

