import pytest
from unittest.mock import MagicMock, patch
from services.container_manager import ContainerManager
import docker

# Mocking the ContainerManager dependencies
@pytest.fixture
def mock_docker():
    with patch("services.container_manager.docker") as mock:
        yield mock

@pytest.fixture
def mock_os():
    with patch("services.container_manager.os") as mock:
        # Default behavior: path exists returns False, expanduser returns input
        mock.path.exists.return_value = False
        mock.path.expanduser.side_effect = lambda x: x
        mock.getenv.return_value = None
        mock.path.join.side_effect = lambda *args: "/".join(args)
        yield mock

class TestContainerManager:

    def test_init_podman_mounted(self, mock_os, mock_docker):
        """Test initialization with mounted Podman socket."""
        # Setup
        mock_os.path.exists.side_effect = lambda path: path == "/run/podman/podman.sock"

        mock_client = MagicMock()
        mock_client.info.return_value = {"ServerVersion": "Podman 4.0.0"}
        mock_docker.DockerClient.return_value = mock_client

        # Action
        cm = ContainerManager(containers_dir="/tmp/containers")

        # Verify
        mock_docker.DockerClient.assert_called_with(base_url="unix:///run/podman/podman.sock")
        assert cm.client == mock_client
        assert cm.runtime == "podman"

    def test_init_podman_rootless(self, mock_os, mock_docker):
        """Test initialization with rootless Podman socket."""
        # Setup
        mock_os.path.exists.return_value = False
        mock_os.getenv.return_value = "/run/user/1000"

        mock_client = MagicMock()
        mock_client.info.return_value = {"ServerVersion": "Podman 4.0.0"}
        mock_docker.DockerClient.return_value = mock_client

        # Action
        cm = ContainerManager(containers_dir="/tmp/containers")

        # Verify
        expected_socket = "unix:///run/user/1000/podman/podman.sock"
        # Since we are mocking getenv, check if the call matches what we expect
        # Note: The implementation uses os.path.expanduser which we mocked to return identity
        # and os.getenv('XDG_RUNTIME_DIR')

        # Check calls to DockerClient. One of them should be correct.
        # Since the first call (mounted) is skipped (path exists false),
        # The second call is rootless.

        # The implementation:
        # podman_socket = os.path.expanduser(f"unix://{os.getenv('XDG_RUNTIME_DIR', '/run/user/1000')}/podman/podman.sock")
        # client = docker.DockerClient(base_url=podman_socket)

        mock_docker.DockerClient.assert_called_with(base_url=expected_socket)
        assert cm.client == mock_client
        assert cm.runtime == "podman"

    def test_init_podman_rootful_fallback(self, mock_os, mock_docker):
        """Test initialization with rootful Podman socket as fallback."""
        # Setup
        mock_os.path.exists.return_value = False
        mock_os.getenv.return_value = "/run/user/1000"

        # First call (rootless) fails, second call (rootful) succeeds
        mock_client = MagicMock()
        mock_client.info.return_value = {"ServerVersion": "Podman 4.0.0"}

        def docker_client_side_effect(base_url=None, **kwargs):
            if "user" in base_url: # Rootless
                raise Exception("Connection failed")
            if base_url == "unix:///run/podman/podman.sock": # Rootful
                return mock_client
            raise Exception("Unexpected call")

        mock_docker.DockerClient.side_effect = docker_client_side_effect

        # Action
        cm = ContainerManager(containers_dir="/tmp/containers")

        # Verify
        assert cm.client == mock_client
        assert cm.runtime == "podman"

    def test_init_docker_fallback(self, mock_os, mock_docker):
        """Test initialization with Docker fallback."""
        # Setup
        mock_os.path.exists.return_value = False
        mock_docker.DockerClient.side_effect = Exception("Podman not found")

        mock_client = MagicMock()
        mock_client.info.return_value = {"ServerVersion": "Docker 20.10.0"}
        mock_docker.from_env.return_value = mock_client

        # Action
        cm = ContainerManager(containers_dir="/tmp/containers")

        # Verify
        mock_docker.from_env.assert_called_once()
        assert cm.client == mock_client
        assert cm.runtime == "docker"

    def test_init_all_failed(self, mock_os, mock_docker):
        """Test initialization failure when no runtime is found."""
        # Setup
        mock_os.path.exists.return_value = False
        mock_docker.DockerClient.side_effect = Exception("Connection failed")
        mock_docker.from_env.side_effect = Exception("Docker not found")

        # Action & Verify
        with pytest.raises(RuntimeError) as excinfo:
            ContainerManager(containers_dir="/tmp/containers")

        assert "Could not connect to Docker or Podman" in str(excinfo.value)

    def test_detect_runtime_podman(self, mock_os, mock_docker):
        """Test runtime detection for Podman."""
        # Setup
        # Assume docker fallback works for simplicity of setup
        mock_os.path.exists.return_value = False
        mock_docker.DockerClient.side_effect = Exception("Podman not found")

        mock_client = MagicMock()
        mock_client.info.return_value = {"ServerVersion": "Podman 4.5.0"}
        mock_docker.from_env.return_value = mock_client

        # Action
        cm = ContainerManager(containers_dir="/tmp/containers")

        # Verify
        assert cm.runtime == "podman"

    def test_detect_runtime_docker(self, mock_os, mock_docker):
        """Test runtime detection for Docker."""
        # Setup
        mock_os.path.exists.return_value = False
        mock_docker.DockerClient.side_effect = Exception("Podman not found")

        mock_client = MagicMock()
        mock_client.info.return_value = {"ServerVersion": "Docker 24.0.0"}
        mock_docker.from_env.return_value = mock_client

        # Action
        cm = ContainerManager(containers_dir="/tmp/containers")

        # Verify
        assert cm.runtime == "docker"

    def test_detect_runtime_unknown(self, mock_os, mock_docker):
        """Test runtime detection when info fails."""
        # Setup
        mock_os.path.exists.return_value = False
        mock_docker.DockerClient.side_effect = Exception("Podman not found")

        mock_client = MagicMock()
        mock_client.info.side_effect = Exception("Error getting info")
        mock_docker.from_env.return_value = mock_client

        # Action
        cm = ContainerManager(containers_dir="/tmp/containers")

        # Verify
        assert cm.runtime == "unknown"

    def test_wait_for_health_succeeds_on_http_200(self):
        cm = ContainerManager.__new__(ContainerManager)
        container = MagicMock()
        container.name = "test-container"
        container.status = "running"
        container.ports = {"8000/tcp": [{"HostPort": "8123"}]}

        response = MagicMock()
        response.status_code = 200

        with patch("services.container_manager.requests.get", return_value=response), \
             patch("services.container_manager.time.sleep", return_value=None):
            cm._wait_for_health(container, timeout=1)

    def test_wait_for_health_uses_container_dns_probe_first(self):
        cm = ContainerManager.__new__(ContainerManager)
        container = MagicMock()
        container.name = "test-container"
        container.status = "running"
        container.ports = {}
        container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    "comfy-network": {
                        "IPAddress": "172.20.0.12",
                    }
                }
            }
        }

        response = MagicMock()
        response.status_code = 200

        with patch("services.container_manager.requests.get", return_value=response) as mock_get, \
             patch("services.container_manager.time.sleep", return_value=None):
            cm._wait_for_health(container, timeout=1)

        mock_get.assert_called_once_with("http://test-container:8000/health", timeout=2)

    def test_wait_for_health_times_out_when_only_running(self):
        cm = ContainerManager.__new__(ContainerManager)
        container = MagicMock()
        container.name = "test-container"
        container.status = "running"
        container.ports = {"8000/tcp": [{"HostPort": "8123"}]}

        with patch("services.container_manager.requests.get", side_effect=Exception("probe failed")), \
             patch("services.container_manager.time.sleep", return_value=None), \
             patch("services.container_manager.time.time", side_effect=[0, 0.1, 1.1]):
            with pytest.raises(TimeoutError) as excinfo:
                cm._wait_for_health(container, timeout=1)

        assert "did not become healthy" in str(excinfo.value)
