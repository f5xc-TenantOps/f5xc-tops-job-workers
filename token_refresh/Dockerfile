# Use the AWS Lambda Python base image
FROM public.ecr.aws/lambda/python:3.9

# Set the working directory inside the container
WORKDIR /var/task

# Copy the requirements file
COPY requirements.txt .

# Install Python dependencies, including the GitHub-hosted library
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Lambda function code into the container
COPY function.py .

# Set the command for the Lambda runtime
CMD ["function.lambda_handler"]