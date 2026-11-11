import numpy as np
import pytest


def test_mixed_aspect_batch_tracks_resize_and_actual_center_crop():
    from real2sim_builder.calibration.simfoundry import da3_pixel_affines
    matrices=da3_pixel_affines([[4080,3060],[1920,1080]],336,[336,196])
    # DA3 rounds 336x189 up to 336x196, then crops the 336x252 photo.
    first=np.asarray(matrices[0]);second=np.asarray(matrices[1])
    assert first[1,2]==pytest.approx((252/3060-1)/2-28)
    assert second[1,1]==pytest.approx(196/1080)
    for original,A in zip(([4080,3060],[1920,1080]),matrices):
        center=np.r_[(np.asarray(original)-1)/2,1]
        np.testing.assert_allclose(np.asarray(A)@center,[167.5,97.5,1])


def test_unknown_preprocessing_output_grid_is_rejected():
    from real2sim_builder.calibration.simfoundry import da3_pixel_affines
    with pytest.raises(ValueError,match='processed'):
        da3_pixel_affines([[4080,3060]],336,[400,252])
