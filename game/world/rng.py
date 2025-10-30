"""Centralised factories for world random number generators and noise fields."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Callable, Dict

from numpy.random import BitGenerator, Generator, PCG64
from opensimplex import OpenSimplex

BitGeneratorFactory = Callable[[int], BitGenerator]


def _default_bit_generator(seed: int) -> BitGenerator:
    return PCG64(seed)


_BITGEN_MODULUS = 2**128
_NOISE_MODULUS = 2**31


def _stable_hash(value: str, *, modulo: int) -> int:
    """Return a deterministic hash of ``value`` bounded by ``modulo``."""

    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=16).digest()
    return int.from_bytes(digest, "big") % modulo


@dataclass
class WorldRandomness:
    """Provides seeded RNG streams and simplex noise generators."""

    seed: int
    bit_generator_factory: BitGeneratorFactory = _default_bit_generator
    _generators: Dict[str, Generator] = field(default_factory=dict)
    _noise_fields: Dict[str, OpenSimplex] = field(default_factory=dict)

    def _derive_seed(self, namespace: str, *, modulo: int) -> int:
        token = f"{self.seed}:{namespace}"
        derived = _stable_hash(token, modulo=modulo)
        # Ensure the derived seed is not zero where zero has special meaning.
        return derived or 1

    def generator(self, stream: str = "default") -> Generator:
        """Return (and cache) a ``numpy.random.Generator`` for ``stream``."""

        if stream not in self._generators:
            derived_seed = self._derive_seed(f"rng:{stream}", modulo=_BITGEN_MODULUS)
            bit_gen = self.bit_generator_factory(int(derived_seed))
            self._generators[stream] = Generator(bit_gen)
        return self._generators[stream]

    def noise(self, channel: str = "biome") -> OpenSimplex:
        """Return (and cache) an ``OpenSimplex`` noise field for ``channel``."""

        if channel not in self._noise_fields:
            derived_seed = self._derive_seed(f"noise:{channel}", modulo=_NOISE_MODULUS)
            self._noise_fields[channel] = OpenSimplex(seed=derived_seed)
        return self._noise_fields[channel]


__all__ = ["WorldRandomness"]
