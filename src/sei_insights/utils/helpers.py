#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SEI Insights - Utilitários de Apoio
===================================

Funções auxiliares copiadas do coletor SEI ColaboraGov.
"""

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sei-insights")


def normalize_process_number(value: str) -> str:
    """
    Remove espaços desnecessários do número do processo.

    Exemplo:

        " 21260.003436/2026-15 "
            ->
        "21260.003436/2026-15"
    """

    value = value.strip()

    # Remove espaços internos que possam ter sido copiados
    # acidentalmente.
    value = re.sub(r"\s+", "", value)

    return value


def safe_filename(
    value: str,
    max_length: int = 180,
) -> str:
    """
    Gera um nome de arquivo seguro para Windows/Linux.

    Caracteres proibidos pelo Windows são substituídos.
    """

    value = value.strip()

    value = re.sub(
        r'[<>:"/\\|?*\x00-\x1F]',
        "_",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    value = value.rstrip(". ")

    if not value:
        value = "arquivo"

    return value[:max_length]


def calculate_sha256(path: Path) -> str:
    """
    Calcula o SHA-256 de um arquivo.

    O arquivo é lido em blocos para evitar consumo desnecessário
    de memória para PDFs grandes.
    """

    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:

            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def extension_from_content_type(
    content_type: Optional[str],
) -> str:
    """
    Converte Content-Type em extensão de arquivo.
    """

    if not content_type:
        return ".bin"

    content_type = (
        content_type
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    extensions = {
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/xml": ".xml",
        "application/xml": ".xml",
        "application/zip": ".zip",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "application/msword": ".doc",
        (
            "application/"
            "vnd.openxmlformats-officedocument.wordprocessingml.document"
        ): ".docx",
        "application/vnd.ms-excel": ".xls",
        (
            "application/"
            "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ): ".xlsx",
    }

    return extensions.get(
        content_type,
        ".bin",
    )


def looks_like_html(data: bytes) -> bool:
    """
    Detecta se uma resposta aparentemente destinada a ser arquivo
    é, na verdade, uma página HTML de erro/login.
    """

    sample = data[:4096].lstrip().lower()

    return (
        sample.startswith(b"<!doctype html")
        or sample.startswith(b"<html")
        or b"<html" in sample[:500]
    )


def unique_path(
    path: Path,
) -> Path:
    """
    Evita sobrescrever um arquivo existente.

    Exemplo:

        despacho.pdf
        despacho_1.pdf
        despacho_2.pdf
    """

    if not path.exists():
        return path

    counter = 1

    while True:

        candidate = path.with_name(
            f"{path.stem}_{counter}"
            f"{path.suffix}"
        )

        if not candidate.exists():
            return candidate

        counter += 1