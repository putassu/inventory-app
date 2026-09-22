"""Приватные object keys; пути и URL из пользовательского ввода не принимаются."""

import asyncio
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

from app.config import get_config


class Storage:
    def __init__(self, config=None):
        self.config = config or get_config()
        self.client = None
        if self.config.storage_backend == "s3":
            self.client = boto3.client(
                "s3",
                endpoint_url=self.config.s3_endpoint,
                aws_access_key_id=self.config.s3_access_key,
                aws_secret_access_key=self.config.s3_secret_key.get_secret_value(),
                config=BotoConfig(
                    connect_timeout=5, read_timeout=30, retries={"max_attempts": 0}, proxies={}
                ),
            )

    def path(self, key):
        root = self.config.media_root.resolve()
        target = (root / key).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError("Недопустимый object key")
        return target

    async def initialize(self):
        if self.client:
            buckets = await asyncio.to_thread(self.client.list_buckets)
            if self.config.s3_bucket not in {b["Name"] for b in buckets["Buckets"]}:
                await asyncio.to_thread(self.client.create_bucket, Bucket=self.config.s3_bucket)
        else:
            self.config.media_root.mkdir(parents=True, exist_ok=True)

    async def put(self, key, data, mime="application/octet-stream"):
        if self.client:
            await asyncio.to_thread(
                self.client.put_object, Bucket=self.config.s3_bucket, Key=key, Body=data, ContentType=mime
            )
        else:
            path = self.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(str(path) + ".partial")
            await asyncio.to_thread(temporary.write_bytes, data)
            temporary.replace(path)

    async def read(self, key):
        if self.client:

            def read_s3():
                result = self.client.get_object(Bucket=self.config.s3_bucket, Key=key)
                try:
                    return result["Body"].read()
                finally:
                    result["Body"].close()

            return await asyncio.to_thread(read_s3)
        return await asyncio.to_thread(self.path(key).read_bytes)

    async def delete(self, key):
        if self.client:
            await asyncio.to_thread(self.client.delete_object, Bucket=self.config.s3_bucket, Key=key)
        else:
            await asyncio.to_thread(self.path(key).unlink, missing_ok=True)

    async def objects(self):
        if self.client:

            def list_s3():
                return [
                    {"key": o["Key"], "modified_at": o["LastModified"], "size": o["Size"]}
                    for page in self.client.get_paginator("list_objects_v2").paginate(
                        Bucket=self.config.s3_bucket
                    )
                    for o in page.get("Contents", [])
                ]

            return await asyncio.to_thread(list_s3)
        from datetime import UTC, datetime

        root = self.config.media_root
        return [
            {
                "key": p.relative_to(root).as_posix(),
                "modified_at": datetime.fromtimestamp(p.stat().st_mtime, UTC),
                "size": p.stat().st_size,
            }
            for p in root.rglob("*")
            if p.is_file()
        ]
