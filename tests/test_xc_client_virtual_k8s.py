"""Tests for XCClient virtual_k8s methods."""

from unittest.mock import patch, MagicMock
from shared.xc_client import XCClient


@patch("shared.xc_client.XCClient._validate_url")
@patch("shared.xc_client.XCClient._whoami")
def test_create_virtual_k8s(mock_whoami, mock_validate):
    """create_virtual_k8s POSTs to correct endpoint."""
    client = XCClient(tenant_url="https://test.console.ves.volterra.io", api_token="tok", validate=False)
    client.post = MagicMock(return_value={"metadata": {"name": "test-vk8s"}})

    payload = {"metadata": {"name": "test-vk8s", "namespace": "ns1"}, "spec": {}}
    result = client.create_virtual_k8s("ns1", payload)

    client.post.assert_called_once_with("/api/config/namespaces/ns1/virtual_k8ss", payload)
    assert result["metadata"]["name"] == "test-vk8s"


@patch("shared.xc_client.XCClient._validate_url")
@patch("shared.xc_client.XCClient._whoami")
def test_get_virtual_k8s(mock_whoami, mock_validate):
    """get_virtual_k8s GETs from correct endpoint."""
    client = XCClient(tenant_url="https://test.console.ves.volterra.io", api_token="tok", validate=False)
    client.get = MagicMock(return_value={"metadata": {"name": "test-vk8s"}})

    result = client.get_virtual_k8s("ns1", "test-vk8s")

    client.get.assert_called_once_with("/api/config/namespaces/ns1/virtual_k8ss/test-vk8s")
    assert result["metadata"]["name"] == "test-vk8s"
