# Copyright (c) 2022-2025, The Isaac Lab Project Developers (https://github.com/isaac-sim/IsaacLab/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause


# Only the transitive functions required by the reference Mimic core. Bodies unchanged.
from __future__ import annotations
import math
import numpy as np
import torch
import torch.nn.functional
from typing import Literal

@torch.jit.script
def normalize(x: torch.Tensor, eps: float = 1e-9) -> torch.Tensor:
    """Normalizes a given input tensor to unit length.

    Args:
        x: Input tensor of shape (N, dims).
        eps: A small value to avoid division by zero. Defaults to 1e-9.

    Returns:
        Normalized tensor of shape (N, dims).
    """
    return x / x.norm(p=2, dim=-1).clamp(min=eps, max=None).unsqueeze(-1)


@torch.jit.script
def matrix_from_quat(quaternions: torch.Tensor) -> torch.Tensor:
    """Convert rotations given as quaternions to rotation matrices.

    Args:
        quaternions: The quaternion orientation in (w, x, y, z). Shape is (..., 4).

    Returns:
        Rotation matrices. The shape is (..., 3, 3).

    Reference:
        https://github.com/facebookresearch/pytorch3d/blob/main/pytorch3d/transforms/rotation_conversions.py#L41-L70
    """
    r, i, j, k = torch.unbind(quaternions, -1)
    # pyre-fixme[58]: `/` is not supported for operand types `float` and `Tensor`.
    two_s = 2.0 / (quaternions * quaternions).sum(-1)

    o = torch.stack(
        (
            1 - two_s * (j * j + k * k),
            two_s * (i * j - k * r),
            two_s * (i * k + j * r),
            two_s * (i * j + k * r),
            1 - two_s * (i * i + k * k),
            two_s * (j * k - i * r),
            two_s * (i * k - j * r),
            two_s * (j * k + i * r),
            1 - two_s * (i * i + j * j),
        ),
        -1,
    )
    return o.reshape(quaternions.shape[:-1] + (3, 3))


@torch.jit.script
def _sqrt_positive_part(x: torch.Tensor) -> torch.Tensor:
    """Returns torch.sqrt(torch.max(0, x)) but with a zero sub-gradient where x is 0.

    Reference:
        https://github.com/facebookresearch/pytorch3d/blob/main/pytorch3d/transforms/rotation_conversions.py#L91-L99
    """
    ret = torch.zeros_like(x)
    positive_mask = x > 0
    ret[positive_mask] = torch.sqrt(x[positive_mask])
    return ret


@torch.jit.script
def quat_from_matrix(matrix: torch.Tensor) -> torch.Tensor:
    """Convert rotations given as rotation matrices to quaternions.

    Args:
        matrix: The rotation matrices. Shape is (..., 3, 3).

    Returns:
        The quaternion in (w, x, y, z). Shape is (..., 4).

    Reference:
        https://github.com/facebookresearch/pytorch3d/blob/main/pytorch3d/transforms/rotation_conversions.py#L102-L161
    """
    if matrix.size(-1) != 3 or matrix.size(-2) != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")

    batch_dim = matrix.shape[:-2]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = torch.unbind(matrix.reshape(batch_dim + (9,)), dim=-1)

    q_abs = _sqrt_positive_part(
        torch.stack(
            [
                1.0 + m00 + m11 + m22,
                1.0 + m00 - m11 - m22,
                1.0 - m00 + m11 - m22,
                1.0 - m00 - m11 + m22,
            ],
            dim=-1,
        )
    )

    # we produce the desired quaternion multiplied by each of r, i, j, k
    quat_by_rijk = torch.stack(
        [
            # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and `int`.
            torch.stack([q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01], dim=-1),
            # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and `int`.
            torch.stack([m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20], dim=-1),
            # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and `int`.
            torch.stack([m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21], dim=-1),
            # pyre-fixme[58]: `**` is not supported for operand types `Tensor` and `int`.
            torch.stack([m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2], dim=-1),
        ],
        dim=-2,
    )

    # We floor here at 0.1 but the exact level is not important; if q_abs is small,
    # the candidate won't be picked.
    flr = torch.tensor(0.1).to(dtype=q_abs.dtype, device=q_abs.device)
    quat_candidates = quat_by_rijk / (2.0 * q_abs[..., None].max(flr))

    # if not for numerical problems, quat_candidates[i] should be same (up to a sign),
    # forall i; we pick the best-conditioned one (with the largest denominator)
    return quat_candidates[torch.nn.functional.one_hot(q_abs.argmax(dim=-1), num_classes=4) > 0.5, :].reshape(
        batch_dim + (4,)
    )


@torch.jit.script
def axis_angle_from_quat(quat: torch.Tensor, eps: float = 1.0e-6) -> torch.Tensor:
    """Convert rotations given as quaternions to axis/angle.

    Args:
        quat: The quaternion orientation in (w, x, y, z). Shape is (..., 4).
        eps: The tolerance for Taylor approximation. Defaults to 1.0e-6.

    Returns:
        Rotations given as a vector in axis angle form. Shape is (..., 3).
        The vector's magnitude is the angle turned anti-clockwise in radians around the vector's direction.

    Reference:
        https://github.com/facebookresearch/pytorch3d/blob/main/pytorch3d/transforms/rotation_conversions.py#L526-L554
    """
    # Modified to take in quat as [q_w, q_x, q_y, q_z]
    # Quaternion is [q_w, q_x, q_y, q_z] = [cos(theta/2), n_x * sin(theta/2), n_y * sin(theta/2), n_z * sin(theta/2)]
    # Axis-angle is [a_x, a_y, a_z] = [theta * n_x, theta * n_y, theta * n_z]
    # Thus, axis-angle is [q_x, q_y, q_z] / (sin(theta/2) / theta)
    # When theta = 0, (sin(theta/2) / theta) is undefined
    # However, as theta --> 0, we can use the Taylor approximation 1/2 - theta^2 / 48
    quat = quat * (1.0 - 2.0 * (quat[..., 0:1] < 0.0))
    mag = torch.linalg.norm(quat[..., 1:], dim=-1)
    half_angle = torch.atan2(mag, quat[..., 0])
    angle = 2.0 * half_angle
    # check whether to apply Taylor approximation
    sin_half_angles_over_angles = torch.where(
        angle.abs() > eps, torch.sin(half_angle) / angle, 0.5 - angle * angle / 48
    )
    return quat[..., 1:4] / sin_half_angles_over_angles.unsqueeze(-1)


@torch.jit.script
def quat_from_angle_axis(angle: torch.Tensor, axis: torch.Tensor) -> torch.Tensor:
    """Convert rotations given as angle-axis to quaternions.

    Args:
        angle: The angle turned anti-clockwise in radians around the vector's direction. Shape is (N,).
        axis: The axis of rotation. Shape is (N, 3).

    Returns:
        The quaternion in (w, x, y, z). Shape is (N, 4).
    """
    theta = (angle / 2).unsqueeze(-1)
    xyz = normalize(axis) * theta.sin()
    w = theta.cos()
    return normalize(torch.cat([w, xyz], dim=-1))


def make_pose(pos: torch.Tensor, rot: torch.Tensor) -> torch.Tensor:
    """Creates transformation matrices from positions and rotation matrices.

    Args:
        pos: Batch of position vectors with last dimension of 3.
        rot: Batch of rotation matrices with last 2 dimensions of (3, 3).

    Returns:
        Batch of pose matrices with last 2 dimensions of (4, 4).
    """
    assert isinstance(pos, torch.Tensor), "Input must be a torch tensor"
    assert isinstance(rot, torch.Tensor), "Input must be a torch tensor"
    assert pos.shape[:-1] == rot.shape[:-2]
    assert pos.shape[-1] == rot.shape[-2] == rot.shape[-1] == 3
    pose = torch.zeros(pos.shape[:-1] + (4, 4), dtype=pos.dtype, device=pos.device)
    pose[..., :3, :3] = rot
    pose[..., :3, 3] = pos
    pose[..., 3, 3] = 1.0
    return pose


def unmake_pose(pose: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Splits transformation matrices into positions and rotation matrices.

    Args:
        pose: Batch of pose matrices with last 2 dimensions of (4, 4).

    Returns:
        Tuple containing:
            - Batch of position vectors with last dimension of 3.
            - Batch of rotation matrices with last 2 dimensions of (3, 3).
    """
    assert isinstance(pose, torch.Tensor), "Input must be a torch tensor"
    return pose[..., :3, 3], pose[..., :3, :3]


def pose_inv(pose: torch.Tensor) -> torch.Tensor:
    """Computes the inverse of transformation matrices.

    The inverse of a pose matrix [R t; 0 1] is [R.T -R.T*t; 0 1].

    Args:
        pose: Batch of pose matrices with last 2 dimensions of (4, 4).

    Returns:
        Batch of inverse pose matrices with last 2 dimensions of (4, 4).
    """
    assert isinstance(pose, torch.Tensor), "Input must be a torch tensor"
    num_axes = len(pose.shape)
    assert num_axes >= 2

    inv_pose = torch.zeros_like(pose)

    # Take transpose of last 2 dimensions
    inv_pose[..., :3, :3] = pose[..., :3, :3].transpose(-1, -2)

    # note: PyTorch matmul wants shapes [..., 3, 3] x [..., 3, 1] -> [..., 3, 1] so we add a dimension and take it away after
    inv_pose[..., :3, 3] = torch.matmul(-inv_pose[..., :3, :3], pose[..., :3, 3:4])[..., 0]
    inv_pose[..., 3, 3] = 1.0
    return inv_pose


def pose_in_A_to_pose_in_B(pose_in_A: torch.Tensor, pose_A_in_B: torch.Tensor) -> torch.Tensor:
    """Converts poses from one coordinate frame to another.

    Transforms matrices representing point C in frame A
    to matrices representing the same point C in frame B.

    Example usage:

    frame_C_in_B = pose_in_A_to_pose_in_B(frame_C_in_A, frame_A_in_B)

    Args:
        pose_in_A: Batch of transformation matrices of point C in frame A.
        pose_A_in_B: Batch of transformation matrices of frame A in frame B.

    Returns:
        Batch of transformation matrices of point C in frame B.
    """
    assert isinstance(pose_in_A, torch.Tensor), "Input must be a torch tensor"
    assert isinstance(pose_A_in_B, torch.Tensor), "Input must be a torch tensor"
    return torch.matmul(pose_A_in_B, pose_in_A)


def quat_slerp(q1: torch.Tensor, q2: torch.Tensor, tau: float) -> torch.Tensor:
    """Performs spherical linear interpolation (SLERP) between two quaternions.

    This function does not support batch processing.

    Args:
        q1: First quaternion in (w, x, y, z) format.
        q2: Second quaternion in (w, x, y, z) format.
        tau: Interpolation coefficient between 0 (q1) and 1 (q2).

    Returns:
        Interpolated quaternion in (w, x, y, z) format.
    """
    assert isinstance(q1, torch.Tensor), "Input must be a torch tensor"
    assert isinstance(q2, torch.Tensor), "Input must be a torch tensor"
    if tau == 0.0:
        return q1
    elif tau == 1.0:
        return q2
    d = torch.dot(q1, q2)
    if abs(abs(d) - 1.0) < torch.finfo(q1.dtype).eps * 4.0:
        return q1
    if d < 0.0:
        # Invert rotation
        d = -d
        q2 *= -1.0
    angle = torch.acos(torch.clamp(d, -1, 1))
    if abs(angle) < torch.finfo(q1.dtype).eps * 4.0:
        return q1
    isin = 1.0 / torch.sin(angle)
    q1 = q1 * torch.sin((1.0 - tau) * angle) * isin
    q2 = q2 * torch.sin(tau * angle) * isin
    q1 = q1 + q2
    return q1


def interpolate_rotations(R1: torch.Tensor, R2: torch.Tensor, num_steps: int, axis_angle: bool = True) -> torch.Tensor:
    """Interpolates between two rotation matrices.

    Args:
        R1: First rotation matrix. (4x4).
        R2: Second rotation matrix. (4x4).
        num_steps: Number of desired interpolated rotations (excluding start and end).
        axis_angle: If True, interpolate in axis-angle representation;
                   otherwise use slerp. Defaults to True.

    Returns:
        Stack of interpolated rotation matrices of shape (num_steps + 1, 4, 4),
        including the start and end rotations.
    """
    assert isinstance(R1, torch.Tensor), "Input must be a torch tensor"
    assert isinstance(R2, torch.Tensor), "Input must be a torch tensor"
    if axis_angle:
        # Delta rotation expressed as axis-angle
        delta_rot_mat = torch.matmul(R2, R1.transpose(-1, -2))
        delta_quat = quat_from_matrix(delta_rot_mat)
        delta_axis_angle = axis_angle_from_quat(delta_quat)

        # Grab angle
        delta_angle = torch.linalg.norm(delta_axis_angle)

        # Fix the axis, and chunk the angle up into steps
        rot_step_size = delta_angle / num_steps

        # Convert into delta rotation matrices, and then convert to absolute rotations
        if delta_angle < 0.05:
            # Small angle - don't bother with interpolation
            rot_steps = torch.stack([R2 for _ in range(num_steps)])
        else:
            # Make sure that axis is a unit vector
            delta_axis = delta_axis_angle / delta_angle
            delta_rot_steps = [
                matrix_from_quat(quat_from_angle_axis(i * rot_step_size, delta_axis)) for i in range(num_steps)
            ]
            rot_steps = torch.stack([torch.matmul(delta_rot_steps[i], R1) for i in range(num_steps)])
    else:
        q1 = quat_from_matrix(R1)
        q2 = quat_from_matrix(R2)
        rot_steps = torch.stack(
            [matrix_from_quat(quat_slerp(q1, q2, tau=float(i) / num_steps)) for i in range(num_steps)]
        )

    # Add in endpoint
    rot_steps = torch.cat([rot_steps, R2[None]], dim=0)

    return rot_steps


def interpolate_poses(
    pose_1: torch.Tensor,
    pose_2: torch.Tensor,
    num_steps: int = None,
    step_size: float = None,
    perturb: bool = False,
) -> tuple[torch.Tensor, int]:
    """Performs linear interpolation between two poses.

    Args:
        pose_1: 4x4 start pose.
        pose_2: 4x4 end pose.
        num_steps: If provided, specifies the number of desired interpolated points.
                  Passing 0 corresponds to no interpolation. If None, step_size must be provided.
        step_size: If provided, determines number of steps based on distance between poses.
        perturb: If True, randomly perturbs interpolated position points.

    Returns:
        Tuple containing:
            - Array of shape (N + 2, 4, 4) corresponding to the interpolated pose path.
            - Number of interpolated points (N) in the path.
    """
    assert isinstance(pose_1, torch.Tensor), "Input must be a torch tensor"
    assert isinstance(pose_2, torch.Tensor), "Input must be a torch tensor"
    assert step_size is None or num_steps is None

    pos1, rot1 = unmake_pose(pose_1)
    pos2, rot2 = unmake_pose(pose_2)

    if num_steps == 0:
        # Skip interpolation
        return (
            torch.cat([pos1[None], pos2[None]], dim=0),
            torch.cat([rot1[None], rot2[None]], dim=0),
            num_steps,
        )

    delta_pos = pos2 - pos1
    if num_steps is None:
        assert torch.norm(delta_pos) > 0
        num_steps = math.ceil(torch.norm(delta_pos) / step_size)

    num_steps += 1  # Include starting pose
    assert num_steps >= 2

    # Linear interpolation of positions
    pos_step_size = delta_pos / num_steps
    grid = torch.arange(num_steps, dtype=torch.float32)
    if perturb:
        # Move interpolation grid points by up to half-size forward or backward
        perturbations = torch.rand(num_steps - 2) - 0.5
        grid[1:-1] += perturbations
    pos_steps = torch.stack([pos1 + grid[i] * pos_step_size for i in range(num_steps)])

    # Add in endpoint
    pos_steps = torch.cat([pos_steps, pos2[None]], dim=0)

    # Interpolate rotations
    rot_steps = interpolate_rotations(R1=rot1, R2=rot2, num_steps=num_steps, axis_angle=True)

    pose_steps = make_pose(pos_steps, rot_steps)
    return pose_steps, num_steps - 1
