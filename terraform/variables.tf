variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP zone for the zonal cluster (cheaper than regional)"
  type        = string
  default     = "us-central1-a"
}

variable "cluster_name" {
  description = "Name of the GKE cluster"
  type        = string
  default     = "infra-hub-test"
}

variable "node_count" {
  description = "Initial number of nodes in the default pool"
  type        = number
  default     = 2
}

variable "machine_type" {
  description = "Node machine type"
  type        = string
  default     = "e2-small"
}

