terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- The GKE cluster (control plane) ---------------------------------
# Best practice: create the cluster with its default node pool removed,
# then attach our own managed node pool. This lets Terraform manage the
# node pool independently (e.g. resize) without recreating the cluster.
resource "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false

  # NEW: enable Workload Identity at the cluster level
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "primary_nodes" {
  name       = "default-pool"
  location   = var.region
  cluster    = google_container_cluster.primary.name
  node_count = var.node_count

  node_config {
    machine_type = var.machine_type
    disk_size_gb = 30
    spot         = true
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    # NEW: nodes must expose the GKE metadata server for WI to work
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}

