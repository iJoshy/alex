variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "openai_api_key" {
  description = "OpenAI API key for the researcher agent"
  type        = string
  sensitive   = true
}

variable "alex_api_endpoint" {
  description = "Alex API endpoint from Part 3"
  type        = string
}

variable "alex_api_key" {
  description = "Alex API key from Part 3"
  type        = string
  sensitive   = true
}

variable "scheduler_enabled" {
  description = "Enable automated research scheduler"
  type        = bool
  default     = false
}

variable "bedrock_model_id" {
  description = "Bedrock model ID used by researcher (without the bedrock/ prefix)"
  type        = string
  default     = "openai.gpt-oss-120b-1:0"
}

variable "bedrock_region" {
  description = "Bedrock region for model invocation"
  type        = string
  default     = "us-west-2"
}
