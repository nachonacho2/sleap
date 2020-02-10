"""Transformers for image resizing and padding."""

import tensorflow as tf
import attr
from typing import List, Text, Optional, Tuple


def find_padding_for_stride(
    image_height: int, image_width: int, max_stride: int
) -> Tuple[int, int]:
    """Compute padding required to ensure image is divisible by a stride.

    This function is useful for determining how to pad images such that they will not
    have issues with divisibility after repeated pooling steps.

    Args:
        image_height: Scalar integer specifying the image height (rows).
        image_width: Scalar integer specifying the image height (columns).
        max_stride: Scalar integer specifying the maximum stride that the image must be
            divisible by.

    Returns:
        A tuple of (pad_bottom, pad_right), integers with the number of pixels that the
        image would need to be padded by to meet the divisibility requirement.
    """
    pad_bottom = (max_stride - (image_height % max_stride)) % max_stride
    pad_right = (max_stride - (image_width % max_stride)) % max_stride
    return pad_bottom, pad_right


def pad_to_stride(image: tf.Tensor, max_stride: int) -> tf.Tensor:
    """Pad an image to meet a max stride constraint.

    This is useful for ensuring there is no size mismatch between an image and the
    output tensors after multiple downsampling and upsampling steps.

    Args:
        image: Single image tensor of shape (height, width, channels).
        max_stride: Scalar integer specifying the maximum stride that the image must be
            divisible by. This is the ratio between the length of the image and the
            length of the smallest tensor it is converted to. This is typically
            `2 ** n_down_blocks`, where `n_down_blocks` is the number of 2-strided
            reduction layers in the model.

    Returns:
        The input image with 0-padding applied to the bottom and/or right such that the
        new shape's height and width are both divisible by `max_stride`.
    """
    pad_bottom, pad_right = find_padding_for_stride(
        image_height=tf.shape(image)[0],
        image_width=tf.shape(image)[1],
        max_stride=max_stride,
    )
    if pad_bottom > 0 or pad_right > 0:
        paddings = tf.cast([[0, pad_bottom], [0, pad_right], [0, 0]], tf.int32)
        image = tf.pad(image, paddings, mode="CONSTANT", constant_values=0)
    return image


def resize_image(image: tf.Tensor, scale: tf.Tensor) -> tf.Tensor:
    """Rescale an image by a scale factor.

    This function is primarily a convenience wrapper for `tf.image.resize` that
    calculates the new shape from the scale factor.

    Args:
        image: Single image tensor of shape (height, width, channels).
        scale: Factor to resize the image dimensions by, specified as either a float
            scalar or as a 2-tuple of [scale_x, scale_y]. If a scalar is provided, both
            dimensions are resized by the same factor.

    Returns:
        The resized image tensor of the same dtype but scaled height and width.

    See also: tf.image.resize
    """
    height = tf.shape(image)[0]
    width = tf.shape(image)[1]
    new_size = tf.reverse(
        tf.cast(
            tf.cast([width, height], tf.float32) * tf.cast(scale, tf.float32), tf.int32
        ),
        [0],
    )
    return tf.cast(
        tf.image.resize(
            image,
            size=new_size,
            method="bilinear",
            preserve_aspect_ratio=False,
            antialias=False,
        ),
        image.dtype,
    )


@attr.s(auto_attribs=True)
class Resizer:
    """Data transformer to resize or pad images.

    This is useful as a transformation to data streams that require resizing or padding
    in order to be downsampled or meet divisibility criteria.

    Attributes:
        image_key: String name of the key containing the images to resize.
        scale: Scalar float specifying scaling factor to resize images by.
        pad_to_stride: Maximum stride in a model that the images must be divisible by.
            If > 1, this will pad the bottom and right of the images to ensure they meet
            this divisibility criteria. Padding is applied after the scaling specified
            in the `scale` attribute.
    """

    image_key: Text = "image"
    scale: float = 1.0
    pad_to_stride: int = 1

    @property
    def input_keys(self) -> List[Text]:
        """Return the keys that incoming elements are expected to have."""
        return [self.image_key]

    @property
    def output_keys(self) -> List[Text]:
        """Return the keys that outgoing elements will have."""
        return self.input_keys

    def transform_dataset(self, ds_input: tf.data.Dataset) -> tf.data.Dataset:
        """Create a dataset that contains centroids computed from the inputs.

        Args:
            ds_input: A dataset with image key specified in the `image_key` attribute.

        Returns:
            A `tf.data.Dataset` with elements containing the same images with
            normalization applied.
        """

        def resize(example):
            """Local processing function for dataset mapping."""
            if self.scale != 1.0:
                # Ensure image is rank-3 for resizing ops.
                example[self.image_key] = tf.ensure_shape(
                    example[self.image_key], (None, None, None)
                )
                example[self.image_key] = resize_image(
                    example[self.image_key], self.scale
                )
            if self.pad_to_stride > 1:
                example[self.image_key] = pad_to_stride(
                    example[self.image_key], max_stride=self.pad_to_stride
                )
            return example

        # Map transformation.
        ds_output = ds_input.map(
            resize, num_parallel_calls=tf.data.experimental.AUTOTUNE
        )
        return ds_output
