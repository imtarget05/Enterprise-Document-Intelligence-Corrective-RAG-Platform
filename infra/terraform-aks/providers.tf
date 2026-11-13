terraform {
  backend "azurerm" {
    resource_group_name  = "tfstate-smartdoc"
    storage_account_name = "tfstatesmartdoc"
    container_name       = "tfstate"
    key                  = "smartdoc.terraform.state"
  }
}
