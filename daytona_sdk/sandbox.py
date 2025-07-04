import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Dict, Optional

from daytona_api_client import PortPreviewUrl, ToolboxApi
from daytona_api_client import Workspace as ApiSandbox
from daytona_api_client import WorkspaceApi as SandboxApi
from daytona_api_client import WorkspaceInfo as ApiSandboxInfo
from daytona_api_client import WorkspaceState as SandboxState
from deprecated import deprecated
from pydantic import Field

from ._utils.enum import to_enum
from ._utils.errors import intercept_errors
from ._utils.timeout import with_timeout
from .common.errors import DaytonaError
from .filesystem import FileSystem
from .git import Git
from .lsp_server import LspLanguageId, LspServer
from .process import Process
from .protocols import SandboxCodeToolbox
from typing import Optional

@dataclass
class SandboxTargetRegion(str, Enum):
    """Target regions for Sandboxes

    **Enum Members**:
        - `EU` ("eu")
        - `US` ("us")
        - `ASIA` ("asia")
    """

    EU = "eu"
    US = "us"
    ASIA = "asia"

    def __str__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, str):
            return self.value == other
        return super().__eq__(other)


@dataclass
class SandboxResources:
    """Resources allocated to a Sandbox.

    Attributes:
        cpu (str): Nu, "1", "2").
        gpu (Optional[str]): Number of GPUs allocated mber of CPU cores allocated (e.g.(e.g., "1") or None if no GPU.
        memory (str): Amount of memory allocated with unit (e.g., "2Gi", "4Gi").
        disk (str): Amount of disk space allocated with unit (e.g., "10Gi", "20Gi").

    Example:
        ```python
        resources = SandboxResources(
            cpu="2",
            gpu="1",
            memory="4Gi",
            disk="20Gi"
        )
        ```
    """

    cpu: str
    memory: str
    disk: str
    gpu: Optional[str] = None


class SandboxInfo(ApiSandboxInfo):
    """Structured information about a Sandbox.

    Attributes:
        id (str): Unique identifier for the Sandbox.
        image (str): Docker image used for the Sandbox.
        user (str): OS user running in the Sandbox.
        env (Dict[str, str]): Environment variables set in the Sandbox.
        labels (Dict[str, str]): Custom labels attached to the Sandbox.
        public (bool): Whether the Sandbox is publicly accessible.
        target (str): Target environment where the Sandbox runs.
        resources (SandboxResources): Resource allocations for the Sandbox.
        state (str): Current state of the Sandbox (e.g., "started", "stopped").
        error_reason (Optional[str]): Error message if Sandbox is in error state.
        snapshot_state (Optional[str]): Current state of Sandbox snapshot.
        snapshot_created_at (Optional[str]): When the snapshot was created.
        node_domain (str): Domain name of the Sandbox node.
        region (str): Region of the Sandbox node.
        class_name (str): Sandbox class.
        updated_at (str): When the Sandbox was last updated.
        last_snapshot (Optional[str]): When the last snapshot was created.
        auto_stop_interval (int): Auto-stop interval in minutes.

    Example:
        ```python
        sandbox = daytona.create()
        info = sandbox.info()
        print(f"Sandbox {info.id} is {info.state}")
        print(f"Resources: {info.resources.cpu} CPU, {info.resources.memory} RAM")
        ```
    """

    id: str
    name: Annotated[
        str,
        Field(
            default="",
            deprecated="The `name` field is deprecated.",
        ),
    ]
    image: Optional[str] = "adamcohenhillel/kortix-suna:0.0.20"
    user: str
    env: Dict[str, str]
    labels: Dict[str, str]
    public: bool
    target: SandboxTargetRegion
    resources: SandboxResources
    state: SandboxState
    error_reason: Optional[str]
    snapshot_state: Optional[str]
    snapshot_created_at: Optional[str]
    node_domain: str
    region: str
    class_name: str
    updated_at: str
    last_snapshot: Optional[str]
    auto_stop_interval: int
    provider_metadata: Annotated[
        Optional[str],
        Field(
            deprecated=(
                "The `provider_metadata` field is deprecated. Use `state`, `node_domain`, `region`, `class_name`,"
                " `updated_at`, `last_snapshot`, `resources`, `auto_stop_interval` instead."
            )
        ),
    ]


class SandboxInstance(ApiSandbox):
    """Represents a Daytona Sandbox instance."""

    info: Optional[SandboxInfo]


class Sandbox:
    """Represents a Daytona Sandbox.

    Attributes:
        id (str): Unique identifier for the Sandbox.
        instance (SandboxInstance): The underlying Sandbox instance.
        code_toolbox (SandboxCodeToolbox): Language-specific toolbox implementation.
        fs (FileSystem): File system operations interface.
        git (Git): Git operations interface.
        process (Process): Process execution interface.
    """

    def __init__(
        self,
        id: str,
        instance: SandboxInstance,
        sandbox_api: SandboxApi,
        toolbox_api: ToolboxApi,
        code_toolbox: SandboxCodeToolbox,
    ):
        """Initialize a new Sandbox instance.

        Args:
            id (str): Unique identifier for the Sandbox.
            instance (SandboxInstance): The underlying Sandbox instance.
            sandbox_api (SandboxApi): API client for Sandbox operations.
            toolbox_api (ToolboxApi): API client for toolbox operations.
            code_toolbox (SandboxCodeToolbox): Language-specific toolbox implementation.
        """
        self.id = id
        self.instance = instance
        self.sandbox_api = sandbox_api
        self.toolbox_api = toolbox_api
        self._code_toolbox = code_toolbox

        self.fs = FileSystem(instance, toolbox_api)
        self.git = Git(self, toolbox_api, instance)
        self.process = Process(code_toolbox, toolbox_api, instance)

    def info(self) -> SandboxInfo:
        """Gets structured information about the Sandbox.

        Returns:
            SandboxInfo: Detailed information about the Sandbox including its
                configuration, resources, and current state.

        Example:
            ```python
            info = sandbox.info()
            print(f"Sandbox {info.id}:")
            print(f"State: {info.state}")
            print(f"Resources: {info.resources.cpu} CPU, {info.resources.memory} RAM")
            ```
        """
        instance = self.sandbox_api.get_workspace(self.id)
        return Sandbox.to_sandbox_info(instance)

    @intercept_errors(message_prefix="Failed to get sandbox root directory: ")
    def get_user_root_dir(self) -> str:
        """Gets the root directory path for the logged in user inside the Sandbox.

        Returns:
            str: The absolute path to the Sandbox root directory for the logged in user.

        Example:
            ```python
            root_dir = sandbox.get_user_root_dir()
            print(f"Sandbox root: {root_dir}")
            ```
        """
        response = self.toolbox_api.get_project_dir(self.instance.id)
        return response.dir

    @deprecated(
        reason="Method is deprecated. Use `get_user_root_dir` instead. This method will be removed in a future version."
    )
    def get_workspace_root_dir(self) -> str:
        return self.get_user_root_dir()

    def create_lsp_server(
        self, language_id: LspLanguageId, path_to_project: str
    ) -> LspServer:
        """Creates a new Language Server Protocol (LSP) server instance.

        The LSP server provides language-specific features like code completion,
        diagnostics, and more.

        Args:
            language_id (LspLanguageId): The language server type (e.g., LspLanguageId.PYTHON).
            path_to_project (str): Absolute path to the project root directory.

        Returns:
            LspServer: A new LSP server instance configured for the specified language.

        Example:
            ```python
            lsp = sandbox.create_lsp_server("python", "/workspace/project")
            ```
        """
        return LspServer(language_id, path_to_project, self.toolbox_api, self.instance)

    @intercept_errors(message_prefix="Failed to set labels: ")
    def set_labels(self, labels: Dict[str, str]) -> Dict[str, str]:
        """Sets labels for the Sandbox.

        Labels are key-value pairs that can be used to organize and identify Sandboxes.

        Args:
            labels (Dict[str, str]): Dictionary of key-value pairs representing Sandbox labels.

        Returns:
            Dict[str, str]: Dictionary containing the updated Sandbox labels.

        Example:
            ```python
            new_labels = sandbox.set_labels({
                "project": "my-project",
                "environment": "development",
                "team": "backend"
            })
            print(f"Updated labels: {new_labels}")
            ```
        """
        # Convert all values to strings and create the expected labels structure
        string_labels = {
            k: str(v).lower() if isinstance(v, bool) else str(v)
            for k, v in labels.items()
        }
        labels_payload = {"labels": string_labels}
        return self.sandbox_api.replace_labels(self.id, labels_payload)

    @intercept_errors(message_prefix="Failed to start sandbox: ")
    @with_timeout(
        error_message=lambda self, timeout: (
            f"Sandbox {self.id} failed to start within the {timeout} seconds timeout period"
        )
    )
    def start(self, timeout: Optional[float] = 60):
        """Starts the Sandbox and waits for it to be ready.

        Args:
            timeout (Optional[float]): Maximum time to wait in seconds. 0 means no timeout. Default is 60 seconds.

        Raises:
            DaytonaError: If timeout is negative. If sandbox fails to start or times out.

        Example:
            ```python
            sandbox = daytona.get_current_sandbox("my-sandbox")
            sandbox.start(timeout=40)  # Wait up to 40 seconds
            print("Sandbox started successfully")
            ```
        """
        self.sandbox_api.start_workspace(self.id, _request_timeout=timeout or None)
        self.wait_for_sandbox_start()

    @intercept_errors(message_prefix="Failed to stop sandbox: ")
    @with_timeout(
        error_message=lambda self, timeout: (
            f"Sandbox {self.id} failed to stop within the {timeout} seconds timeout period"
        )
    )
    def stop(self, timeout: Optional[float] = 60):
        """Stops the Sandbox and waits for it to be fully stopped.

        Args:
            timeout (Optional[float]): Maximum time to wait in seconds. 0 means no timeout. Default is 60 seconds.

        Raises:
            DaytonaError: If timeout is negative; If sandbox fails to stop or times out

        Example:
            ```python
            sandbox = daytona.get_current_sandbox("my-sandbox")
            sandbox.stop()
            print("Sandbox stopped successfully")
            ```
        """
        self.sandbox_api.stop_workspace(self.id, _request_timeout=timeout or None)
        self.wait_for_sandbox_stop()

    def delete(self) -> None:
        """Deletes the Sandbox."""
        self.sandbox_api.delete_workspace(self.id, force=True)

    @deprecated(
        reason=(
            "Method is deprecated. Use `wait_for_sandbox_start` instead. This method will be removed in a future"
            " version."
        )
    )
    def wait_for_workspace_start(self, timeout: Optional[float] = 60) -> None:
        """Waits for the Sandbox to reach the 'started' state. Polls the Sandbox status until it
        reaches the 'started' state, encounters an error or times out.

        Args:
            timeout (Optional[float]): Maximum time to wait in seconds. 0 means no timeout. Default is 60 seconds.

        Raises:
            DaytonaError: If timeout is negative; If Sandbox fails to start or times out
        """
        self.wait_for_sandbox_start(timeout)

    @intercept_errors(message_prefix="Failure during waiting for sandbox to start: ")
    @with_timeout(
        error_message=lambda self, timeout: (
            f"Sandbox {self.id} failed to become ready within the {timeout} seconds timeout period"
        )
    )
    def wait_for_sandbox_start(
        self,
        timeout: Optional[float] = 60,  # pylint: disable=unused-argument
    ) -> None:
        """Waits for the Sandbox to reach the 'started' state. Polls the Sandbox status until it
        reaches the 'started' state, encounters an error or times out.

        Args:
            timeout (Optional[float]): Maximum time to wait in seconds. 0 means no timeout. Default is 60 seconds.

        Raises:
            DaytonaError: If timeout is negative; If Sandbox fails to start or times out
        """
        state = None
        while state != "started":
            response = self.sandbox_api.get_workspace(self.id)
            state = response.state

            if state == "error":
                raise DaytonaError(
                    f"Sandbox {self.id} failed to start with state: {state}, error reason: {response.error_reason}"
                )

            time.sleep(0.1)  # Wait 100ms between checks

    @deprecated(
        reason=(
            "Method is deprecated. Use `wait_for_sandbox_stop` instead. This method will be removed in a future"
            " version."
        )
    )
    def wait_for_workspace_stop(self, timeout: Optional[float] = 60) -> None:
        """Waits for the Sandbox to reach the 'stopped' state. Polls the Sandbox status until it
        reaches the 'stopped' state, encounters an error or times out. It will wait up to 60 seconds
        for the Sandbox to stop.

        Args:
            timeout (Optional[float]): Maximum time to wait in seconds. 0 means no timeout. Default is 60 seconds.

        Raises:
            DaytonaError: If timeout is negative. If Sandbox fails to stop or times out.
        """
        self.wait_for_sandbox_stop(timeout)

    @intercept_errors(message_prefix="Failure during waiting for sandbox to stop: ")
    @with_timeout(
        error_message=lambda self, timeout: (
            f"Sandbox {self.id} failed to become stopped within the {timeout} seconds timeout period"
        )
    )
    def wait_for_sandbox_stop(
        self,
        timeout: Optional[float] = 60,  # pylint: disable=unused-argument
    ) -> None:
        """Waits for the Sandbox to reach the 'stopped' state. Polls the Sandbox status until it
        reaches the 'stopped' state, encounters an error or times out. It will wait up to 60 seconds
        for the Sandbox to stop.

        Args:
            timeout (Optional[float]): Maximum time to wait in seconds. 0 means no timeout. Default is 60 seconds.

        Raises:
            DaytonaError: If timeout is negative. If Sandbox fails to stop or times out.
        """
        state = None
        while state != "stopped":
            try:
                response = self.sandbox_api.get_workspace(self.id)
                state = response.state

                if state == "error":
                    raise DaytonaError(
                        f"Sandbox {self.id} failed to stop with status: {state}, error reason: {response.error_reason}"
                    )
            except Exception as e:
                # If there's a validation error, continue waiting
                if "validation error" not in str(e):
                    raise e

            time.sleep(0.1)  # Wait 100ms between checks

    @intercept_errors(message_prefix="Failed to set auto-stop interval: ")
    def set_autostop_interval(self, interval: int) -> None:
        """Sets the auto-stop interval for the Sandbox.

        The Sandbox will automatically stop after being idle (no new events) for the specified interval.
        Events include any state changes or interactions with the Sandbox through the SDK.
        Interactions using Sandbox Previews are not included.

        Args:
            interval (int): Number of minutes of inactivity before auto-stopping.
                Set to 0 to disable auto-stop. Defaults to 15.

        Raises:
            DaytonaError: If interval is negative

        Example:
            ```python
            # Auto-stop after 1 hour
            sandbox.set_autostop_interval(60)
            # Or disable auto-stop
            sandbox.set_autostop_interval(0)
            ```
        """
        if not isinstance(interval, int) or interval < 0:
            raise DaytonaError("Auto-stop interval must be a non-negative integer")

        self.sandbox_api.set_autostop_interval(self.id, interval)
        self.instance.auto_stop_interval = interval

    @intercept_errors(message_prefix="Failed to get preview link: ")
    def get_preview_link(self, port: int) -> PortPreviewUrl:
        """Retrieves the preview link for the sandbox at the specified port. If the port is closed,
        it will be opened automatically. For private sandboxes, a token is included to grant access
        to the URL.

        Args:
            port (int): The port to open the preview link on.

        Returns:
            PortPreviewUrl: The response object for the preview link, which includes the `url`
            and the `token` (to access private sandboxes).

        Example:
            ```python
            preview_link = sandbox.get_preview_link(3000)
            print(f"Preview URL: {preview_link.url}")
            print(f"Token: {preview_link.token}")
            ```
        """
        return self.sandbox_api.get_port_preview_url(self.id, port)

    @intercept_errors(message_prefix="Failed to archive sandbox: ")
    def archive(self) -> None:
        """Archives the sandbox, making it inactive and preserving its state. When sandboxes are
        archived, the entire filesystem state is moved to cost-effective object storage, making it
        possible to keep sandboxes available for an extended period. The tradeoff between archived
        and stopped states is that starting an archived sandbox takes more time, depending on its size.
        Sandbox must be stopped before archiving.
        """
        self.sandbox_api.archive_workspace(self.id)

    @staticmethod
    def to_sandbox_info(instance: ApiSandbox) -> SandboxInfo:
        """Converts an API Sandbox instance to a SandboxInfo object.

        Args:
            instance (ApiSandbox): The API Sandbox instance to convert

        Returns:
            SandboxInfo: The converted SandboxInfo object
        """
        provider_metadata = json.loads(instance.info.provider_metadata or "{}")

        # Extract resources with defaults
        resources = SandboxResources(
            cpu=str(instance.cpu or "1"),
            gpu=str(instance.gpu) if instance.gpu else None,
            memory=str(instance.memory or "2") + "Gi",
            disk=str(instance.disk or "10") + "Gi",
        )

        enum_target = to_enum(SandboxTargetRegion, instance.target)

        return SandboxInfo(
            id=instance.id,
            image=instance.image,
            user=instance.user,
            env=instance.env or {},
            labels=instance.labels or {},
            public=instance.public,
            target=enum_target or instance.target,
            resources=resources,
            state=instance.state,
            error_reason=instance.error_reason,
            snapshot_state=instance.snapshot_state,
            snapshot_created_at=instance.snapshot_created_at,
            auto_stop_interval=instance.auto_stop_interval,
            created=instance.info.created or "",
            node_domain=provider_metadata.get("nodeDomain", ""),
            region=provider_metadata.get("region", ""),
            class_name=provider_metadata.get("class", ""),
            updated_at=provider_metadata.get("updatedAt", ""),
            last_snapshot=provider_metadata.get("lastSnapshot"),
            provider_metadata=instance.info.provider_metadata,
        )
