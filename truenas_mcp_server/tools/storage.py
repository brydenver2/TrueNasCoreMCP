"""
Storage management tools for TrueNAS
"""

from typing import Dict, Any, Optional, List

from ..exceptions import TrueNASValidationError, TrueNASNotFoundError
from .base import BaseTool, tool_handler


class StorageTools(BaseTool):
    """Tools for managing TrueNAS storage (pools, datasets, volumes)"""

    def _tool(self, name: str, description: str, parameters: Dict[str, Any]):
        return (name, getattr(self, name), description, parameters)
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for storage management"""
        return [
            self._tool(
                "list_pools",
                "List all storage pools",
                {
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "Max items to return (default: 100, max: 500)"
                    },
                    "offset": {
                        "type": "integer",
                        "required": False,
                        "description": "Items to skip for pagination"
                    }
                }
            ),
            self._tool(
                "get_pool",
                "Get a single pool by name",
                {
                    "pool_name": {"type": "string", "required": True}
                }
            ),
            self._tool(
                "get_pool_status",
                "Get detailed status of a specific pool",
                {
                    "pool_name": {"type": "string", "required": True}
                }
            ),
            self._tool(
                "list_datasets",
                "List all datasets",
                {
                    "limit": {
                        "type": "integer",
                        "required": False,
                        "description": "Max items to return (default: 100, max: 500)"
                    },
                    "offset": {
                        "type": "integer",
                        "required": False,
                        "description": "Items to skip for pagination"
                    },
                    "include_children": {
                        "type": "boolean",
                        "required": False,
                        "description": "Include child datasets in response (default: true)"
                    },
                    "pool_name": {
                        "type": "string",
                        "required": False,
                        "description": "Filter datasets by pool"
                    }
                }
            ),
            self._tool(
                "get_dataset",
                "Get detailed information about a dataset",
                {
                    "dataset": {"type": "string", "required": True},
                    "include_children": {
                        "type": "boolean",
                        "required": False,
                        "description": "Include child datasets in response (default: true)"
                    }
                }
            ),
            self._tool(
                "create_dataset",
                "Create a new dataset",
                {
                    "pool_name": {"type": "string", "required": True},
                    "dataset_name": {"type": "string", "required": True},
                    "compression": {"type": "string", "required": False},
                    "quota": {"type": "string", "required": False},
                    "recordsize": {"type": "string", "required": False}
                }
            ),
            self._tool(
                "delete_dataset",
                "Delete a dataset",
                {
                    "dataset": {"type": "string", "required": True},
                    "recursive": {"type": "boolean", "required": False}
                }
            ),
            self._tool(
                "update_dataset",
                "Update dataset properties",
                {
                    "dataset": {"type": "string", "required": True},
                    "properties": {"type": "object", "required": True}
                }
            ),
            self._tool(
                "set_quota",
                "Set a quota on a dataset",
                {
                    "dataset_id": {"type": "string", "required": True},
                    "quota": {"type": "string", "required": True},
                    "hard": {"type": "boolean", "required": False}
                }
            )
        ]
    
    @tool_handler
    async def list_pools(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """
        List all storage pools

        Args:
            limit: Maximum items to return (default: 100, max: 500)
            offset: Number of items to skip for pagination

        Returns:
            Dictionary containing list of pools with their status
        """
        await self.ensure_initialized()

        pools = await self.client.get("/pool")

        pool_list = []
        for pool in pools:
            # Calculate usage percentage
            size = pool.get("size", 0)
            allocated = pool.get("allocated", 0)
            free = pool.get("free", 0)
            usage_percent = (allocated / size * 100) if size > 0 else 0

            pool_info = {
                "name": pool.get("name"),
                "status": pool.get("status"),
                "healthy": pool.get("healthy"),
                "encrypted": pool.get("encrypt", 0) > 0,
                "size": self.format_size(size),
                "allocated": self.format_size(allocated),
                "free": self.format_size(free),
                "usage_percent": round(usage_percent, 2),
                "fragmentation": pool.get("fragmentation"),
                "scan": pool.get("scan", {}).get("state") if pool.get("scan") else None,
                "topology": {
                    "data_vdevs": len(pool.get("topology", {}).get("data", [])),
                    "cache_vdevs": len(pool.get("topology", {}).get("cache", [])),
                    "log_vdevs": len(pool.get("topology", {}).get("log", [])),
                    "spare_vdevs": len(pool.get("topology", {}).get("spare", []))
                }
            }
            pool_list.append(pool_info)

        # Calculate totals (before pagination)
        total_size = sum(p.get("size", 0) for p in pools)
        total_allocated = sum(p.get("allocated", 0) for p in pools)
        total_free = sum(p.get("free", 0) for p in pools)

        # Apply pagination
        paginated_pools, pagination = self.apply_pagination(pool_list, limit, offset)

        return {
            "success": True,
            "pools": paginated_pools,
            "pagination": pagination,
            "metadata": {
                "healthy_pools": sum(1 for p in pool_list if p["healthy"]),
                "degraded_pools": sum(1 for p in pool_list if not p["healthy"]),
                "total_capacity": self.format_size(total_size),
                "total_allocated": self.format_size(total_allocated),
                "total_free": self.format_size(total_free),
                "overall_usage_percent": round((total_allocated / total_size * 100) if total_size > 0 else 0, 2)
            }
        }
    
    @tool_handler
    async def get_pool(self, pool_name: str) -> Dict[str, Any]:
        """Get summarized information for a specific pool."""
        status = await self.get_pool_status({"pool_name": pool_name})
        if not status.get("success"):
            return status
        pool_data = status.get("pool", {})
        summary = {"success": True, **pool_data}
        capacity = pool_data.get("capacity", {})
        if capacity.get("size"):
            summary["size"] = capacity["size"]
        if capacity.get("allocated"):
            summary.setdefault("allocated_display", capacity["allocated"])
        if capacity.get("free"):
            summary.setdefault("free_display", capacity["free"])
        return summary

    @tool_handler
    async def get_pool_status(self, pool_name: str) -> Dict[str, Any]:
        """
        Get detailed status of a specific pool
        
        Args:
            pool_name: Name of the pool
            
        Returns:
            Dictionary containing detailed pool status
        """
        await self.ensure_initialized()
        
        try:
            pool = await self.client.get(f"/pool/id/{pool_name}")
        except Exception:
            # Try getting all pools and finding by name
            pools = await self.client.get("/pool")
            pool = None
            for p in pools:
                if p.get("name") == pool_name:
                    pool = p
                    break
            
            if not pool:
                return {
                    "success": False,
                    "error": f"Pool '{pool_name}' not found"
                }
        
        # Extract detailed information
        size = pool.get("size", 0)
        allocated = pool.get("allocated", 0)
        free = pool.get("free", 0)
        
        # Process topology
        topology = pool.get("topology", {})
        vdev_details = []
        
        for vdev_type in ["data", "cache", "log", "spare"]:
            vdevs = topology.get(vdev_type, [])
            for vdev in vdevs:
                vdev_info = {
                    "type": vdev_type,
                    "name": vdev.get("name"),
                    "status": vdev.get("status"),
                    "devices": []
                }
                for device in vdev.get("children", []):
                    vdev_info["devices"].append({
                        "name": device.get("name"),
                        "status": device.get("status"),
                        "read_errors": device.get("read", 0),
                        "write_errors": device.get("write", 0),
                        "checksum_errors": device.get("checksum", 0)
                    })
                vdev_details.append(vdev_info)
        
        return {
            "success": True,
            "pool": {
                "name": pool.get("name"),
                "id": pool.get("id"),
                "guid": pool.get("guid"),
                "status": pool.get("status"),
                "healthy": pool.get("healthy"),
                "encrypted": pool.get("encrypt", 0) > 0,
                "autotrim": pool.get("autotrim", {}).get("value") if pool.get("autotrim") else None,
                "capacity": {
                    "size": self.format_size(size),
                    "size_bytes": size,
                    "allocated": self.format_size(allocated),
                    "allocated_bytes": allocated,
                    "free": self.format_size(free),
                    "free_bytes": free,
                    "usage_percent": round((allocated / size * 100) if size > 0 else 0, 2),
                    "fragmentation": pool.get("fragmentation")
                },
                "topology": {
                    "vdevs": vdev_details,
                    "summary": {
                        "data_vdevs": len(topology.get("data", [])),
                        "cache_vdevs": len(topology.get("cache", [])),
                        "log_vdevs": len(topology.get("log", [])),
                        "spare_vdevs": len(topology.get("spare", []))
                    }
                },
                "scan": pool.get("scan"),
                "properties": pool.get("properties", {})
            }
        }
    
    @tool_handler
    async def list_datasets(
        self,
        limit: int = 100,
        offset: int = 0,
        include_children: bool = True,
        pool_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all datasets

        Args:
            limit: Maximum items to return (default: 100, max: 500)
            offset: Number of items to skip for pagination
            include_children: Include child datasets in response (default: true)

        Returns:
            Dictionary containing list of datasets
        """
        await self.ensure_initialized()

        datasets = await self.client.get("/pool/dataset")

        dataset_list = []
        for ds in datasets:
            # Calculate usage
            used = ds.get("used", {}).get("parsed") if isinstance(ds.get("used"), dict) else ds.get("used", 0)
            available = ds.get("available", {}).get("parsed") if isinstance(ds.get("available"), dict) else ds.get("available", 0)

            dataset_info = {
                "name": ds.get("name"),
                "pool": ds.get("pool"),
                "type": ds.get("type"),
                "mountpoint": ds.get("mountpoint"),
                "compression": ds.get("compression", {}).get("value") if isinstance(ds.get("compression"), dict) else ds.get("compression"),
                "deduplication": ds.get("deduplication", {}).get("value") if isinstance(ds.get("deduplication"), dict) else ds.get("deduplication"),
                "encrypted": ds.get("encrypted"),
                "used": self.format_size(used) if isinstance(used, (int, float)) else str(used),
                "available": self.format_size(available) if isinstance(available, (int, float)) else str(available),
                "quota": ds.get("quota", {}).get("value") if isinstance(ds.get("quota"), dict) else ds.get("quota"),
            }
            # Only include children if requested
            if include_children:
                dataset_info["children"] = ds.get("children", [])

            dataset_list.append(dataset_info)

        if pool_name:
            dataset_list = [ds for ds in dataset_list if ds.get("pool") == pool_name]

        # Organize by pool (before pagination)
        pools_datasets = {}
        for ds in dataset_list:
            pool = ds["pool"]
            if pool not in pools_datasets:
                pools_datasets[pool] = []
            pools_datasets[pool].append(ds)

        # Apply pagination
        paginated_datasets, pagination = self.apply_pagination(dataset_list, limit, offset)

        return {
            "success": True,
            "datasets": paginated_datasets,
            "pagination": pagination,
            "metadata": {
                "by_pool": {pool: len(datasets) for pool, datasets in pools_datasets.items()},
                "encrypted_datasets": sum(1 for ds in dataset_list if ds.get("encrypted")),
                "compressed_datasets": sum(1 for ds in dataset_list if ds.get("compression") and ds.get("compression") != "off")
            }
        }
    
    @tool_handler
    async def get_dataset(self, dataset: str, include_children: bool = True) -> Dict[str, Any]:
        """
        Get detailed information about a dataset

        Args:
            dataset: Dataset path (e.g., "tank/data")
            include_children: Include child datasets in response (default: true)

        Returns:
            Dictionary containing dataset details
        """
        await self.ensure_initialized()

        datasets = await self.client.get("/pool/dataset")

        target_dataset = None
        for ds in datasets:
            if ds.get("name") == dataset:
                target_dataset = ds
                break

        if not target_dataset:
            return {
                "success": False,
                "error": f"Dataset '{dataset}' not found"
            }

        # Extract all properties
        properties = {}
        for key in ["compression", "deduplication", "atime", "sync", "quota", "refquota",
                   "reservation", "refreservation", "recordsize", "snapdir", "copies",
                   "readonly", "exec", "casesensitivity"]:
            value = target_dataset.get(key)
            if isinstance(value, dict):
                properties[key] = value.get("value")
            else:
                properties[key] = value

        result = {
            "success": True,
            "dataset": {
                "name": target_dataset.get("name"),
                "id": target_dataset.get("id"),
                "pool": target_dataset.get("pool"),
                "type": target_dataset.get("type"),
                "mountpoint": target_dataset.get("mountpoint"),
                "encrypted": target_dataset.get("encrypted"),
                "encryption_root": target_dataset.get("encryption_root"),
                "key_loaded": target_dataset.get("key_loaded"),
                "locked": target_dataset.get("locked"),
                "usage": {
                    "used": target_dataset.get("used", {}).get("value") if isinstance(target_dataset.get("used"), dict) else target_dataset.get("used"),
                    "available": target_dataset.get("available", {}).get("value") if isinstance(target_dataset.get("available"), dict) else target_dataset.get("available"),
                    "referenced": target_dataset.get("referenced", {}).get("value") if isinstance(target_dataset.get("referenced"), dict) else target_dataset.get("referenced"),
                    "usedbysnapshots": target_dataset.get("usedbysnapshots", {}).get("value") if isinstance(target_dataset.get("usedbysnapshots"), dict) else target_dataset.get("usedbysnapshots"),
                    "usedbychildren": target_dataset.get("usedbychildren", {}).get("value") if isinstance(target_dataset.get("usedbychildren"), dict) else target_dataset.get("usedbychildren")
                },
                "properties": properties,
                "snapshot_count": target_dataset.get("snapshot_count", 0),
                "origin": target_dataset.get("origin", {}).get("value") if isinstance(target_dataset.get("origin"), dict) else target_dataset.get("origin")
            }
        }

        # Only include children if requested
        if include_children:
            result["dataset"]["children"] = target_dataset.get("children", [])

        return result
    
    @tool_handler
    async def create_dataset(
        self,
        pool_name: Optional[str] = None,
        dataset_name: Optional[str] = None,
        pool: Optional[str] = None,
        name: Optional[str] = None,
        compression: str = "lz4",
        quota: Optional[str] = None,
        recordsize: str = "128K",
        sync: str = "standard",
        atime: bool = True
    ) -> Dict[str, Any]:
        """
        Create a new dataset
        
        Args:
            pool: Pool name where dataset will be created
            name: Dataset name
            compression: Compression algorithm (lz4, gzip, zstd, off)
            quota: Optional quota (e.g., "10G")
            recordsize: Record size (e.g., "128K")
            sync: Sync mode (standard, always, disabled)
            atime: Enable access time updates
            
        Returns:
            Dictionary containing created dataset information
        """
        await self.ensure_initialized()

        normalized_pool = pool_name or pool
        normalized_name = dataset_name or name

        fields = {
            "pool_name": normalized_pool,
            "dataset_name": normalized_name,
        }
        self._validate_fields(fields, ["pool_name", "dataset_name"])

        dataset_path = f"{normalized_pool}/{normalized_name}"
        dataset_data = {
            "name": dataset_path,
            "type": "FILESYSTEM",
            "compression": compression,
            "sync": sync,
            "atime": atime,
            "recordsize": recordsize
        }

        if quota:
            dataset_data["quota"] = self._parse_size(quota)

        created = await self.client.post("/pool/dataset", dataset_data)

        return {
            "success": True,
            "message": f"Dataset '{dataset_path}' created successfully",
            **created
        }
    
    @tool_handler
    async def delete_dataset(
        self,
        dataset: Optional[str] = None,
        dataset_name: Optional[str] = None,
        recursive: bool = False,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Delete a dataset
        
        Args:
            dataset: Dataset path (e.g., "tank/data")
            recursive: Delete child datasets
            force: Force deletion even if dataset has shares
            
        Returns:
            Dictionary confirming deletion
        """
        await self.ensure_initialized()

        target_name = dataset or dataset_name
        self._validate_fields({"dataset": target_name}, ["dataset"])

        if not self.settings.enable_destructive_operations:
            raise TrueNASValidationError(
                "Destructive operations are disabled. Enable TRUENAS_ENABLE_DESTRUCTIVE_OPS to allow dataset deletion."
            )

        datasets = await self.client.get("/pool/dataset")
        target_dataset = next((ds for ds in datasets if ds.get("name") == target_name), None)

        if not target_dataset:
            raise TrueNASNotFoundError(f"Dataset '{target_name}' not found")

        dataset_id = target_dataset["id"]
        await self.client.delete(f"/pool/dataset/id/{dataset_id}")

        return {
            "success": True,
            "message": f"Dataset '{target_name}' deleted successfully",
            "deleted": {
                "name": target_name,
                "recursive": recursive,
                "force": force,
                "children_deleted": len(target_dataset.get("children", [])) if recursive else 0
            }
        }
    
    @tool_handler
    async def update_dataset(self, dataset: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update dataset properties
        
        Args:
            dataset: Dataset path (e.g., "tank/data")
            properties: Dictionary of properties to update
            
        Returns:
            Dictionary containing updated dataset information
        """
        await self.ensure_initialized()
        
        # Find the dataset
        datasets = await self.client.get("/pool/dataset")
        target_dataset = None
        for ds in datasets:
            if ds.get("name") == dataset:
                target_dataset = ds
                break
        
        if not target_dataset:
            return {
                "success": False,
                "error": f"Dataset '{dataset}' not found"
            }
        
        # Process properties
        processed_props = {}
        for key, value in properties.items():
            if key in ["quota", "refquota", "reservation", "refreservation"] and isinstance(value, str):
                processed_props[key] = self.parse_size(value)
            else:
                processed_props[key] = value
        
        # Update the dataset
        dataset_id = target_dataset["id"]
        updated = await self.client.put(f"/pool/dataset/id/{dataset_id}", processed_props)
        
        return {
            "success": True,
            "message": f"Dataset '{dataset}' updated successfully",
            "updated_properties": list(properties.keys()),
            "dataset": {
                "name": updated.get("name"),
                "id": updated.get("id")
            }
        }

    @tool_handler
    async def set_quota(
        self,
        dataset_id: Optional[str] = None,
        quota: Optional[str] = None,
        hard: bool = True
    ) -> Dict[str, Any]:
        """Set a quota on a dataset."""
        await self.ensure_initialized()

        self._validate_fields({"dataset_id": dataset_id, "quota": quota}, ["dataset_id", "quota"])

        quota_bytes = self._parse_size(quota) if isinstance(quota, str) else quota

        response = await self.client.request(
            "PUT",
            f"/pool/dataset/id/{dataset_id}",
            json={"quota": quota_bytes, "hard": hard}
        )

        return {"success": True, "dataset_id": dataset_id, "hard": hard, **response}

    def _validate_fields(self, data: Dict[str, Any], required: List[str]):
        missing = [field for field in required if not data.get(field)]
        if missing:
            raise TrueNASValidationError(f"Missing required fields: {', '.join(missing)}")

    def _format_size(self, size_bytes: int) -> str:
        """Test helper that wraps BaseTool formatting with single decimal precision."""
        if size_bytes is None:
            return "0.0 B"
        value = float(size_bytes)
        units = ["B", "KB", "MB", "GB", "TB", "PB", "EB"]
        for unit in units:
            if abs(value) < 1024.0:
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{value:.1f} ZB"

    def _parse_size(self, size_str: str) -> int:
        return self.parse_size(size_str)