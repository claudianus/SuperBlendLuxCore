"""This module provides export feature for Blender image objects"""

import tempfile
import os
import bpy
import PyOpenColorIO as ocio
from .. import utils


class ImageExporter:
    """
    This class is a singleton
    """

    temp_images = {}
    # Images handed to SuperLuxCore during the current/last export. SuperLuxCore
    # loads them from files itself, so Blender's decoded pixel buffers
    # can be released for the duration of the render.
    used_images = set()
    _cycles_ocio_configs = {}

    @classmethod
    def _save_to_temp_file(cls, image):
        """Save packed files from an image.

        Nota bene:
        - The input image is supposed to contain exactly ONE packed file.
          This is a design limitation at this stage.
        - We don't use 'image.save', as we don't need the conversion features
          it provides and, on the other hand, we need several formats
          (including dds) that this method does not handle.
        """
        assert image.packed_file

        result = []
        for packed in image.packed_files:

            # Save original filepath
            orig_filepath = packed.filepath

            # Compute key
            # Note: We can't use utils.make_key(image) here because the memory
            # address might be re-used on undo, causing a key collision.
            # The packed payload size is part of the key so edited content
            # (same path/name, different bytes) is not served stale.
            try:
                payload_size = len(packed.data)
            except Exception:
                payload_size = 0
            key = (orig_filepath or f"{image.name}-{packed.tile_number}")
            key += f"-{payload_size}"

            # Check whether packed image has already been exported
            try:
                temp_image = cls.temp_images[key]
            except KeyError:
                # This is a new image
                pass
            else:
                # This is an already exported image
                print(f"[BLC] '{key}' already exported - skip")
                result.append(temp_image.name)
                continue


            # Compute filename extension
            if orig_filepath:
                _, extension = os.path.splitext(orig_filepath)
            else:
                # Generated images do not have a filepath, fallback to
                # file_format
                extension = f".{image.file_format.lower()}"

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=extension
            ) as temp_image:
                packed.filepath = temp_image.name
                print(
                    f"[BLC] Unpacking image '{image.name}' to temp file "
                    f"'{temp_image.name}'"
                )

                try:
                    packed.save()
                except RuntimeError as error:
                    print("[BLC] Warning: could not save image. ", str(error))
                    continue
                finally:
                    # The changes above altered the file path, so we have to
                    # restore the original one
                    packed.filepath = orig_filepath

            # Only store the key once we are sure that everything went OK
            cls.temp_images[key] = temp_image

            result.append(temp_image.name)

        # Design limitation: the rest of BLC assumes there is only one packed
        # file per image, so we'll adapt the output.
        # If one day this limitation is removed, the code above is ready for
        # multiple packed files per image
        if (len(result)) > 1:
            print(
                f"[BLC] Warning: image '{image.name}' contains multiple "
                "packed files but only one will be used"
            )
        if not result:
            # Every unpack failed: returning None here would poison the
            # SuperLuxCore properties with a null filepath downstream. Fail
            # loudly instead (callers already handle OSError).
            raise OSError(
                f"Could not unpack image '{image.name}': "
                "all packed files failed to save"
            )
        return result[0]

    @classmethod
    def export(cls, image, image_user, scene):
        """Export image.

        This is the main method of the module.
        """
        cls.used_images.add(image)

        if image.source == "GENERATED":
            return cls._save_to_temp_file(image)

        if image.source == "FILE":
            if image.packed_file:
                return cls._save_to_temp_file(image)

            try:
                filepath = utils.get_abspath(
                    image.filepath,
                    library=image.library,
                    must_exist=True,
                    must_be_existing_file=True,
                )
                return filepath
            except OSError as error:
                # Make the error message more precise
                raise OSError(
                    f"Could not find image '{image.name}' "
                    f"at path '{image.filepath}' ({error})"
                ) from error

        if image.source == "SEQUENCE":
            # Note: image sequences can never be packed
            try:
                frame = image_user.get_frame(scene)
            except ValueError as error:
                raise RuntimeError(str(error)) from error

            indexed_filepaths = utils.image_sequence_resolve_all(image)
            try:
                if frame < 1:
                    raise IndexError
                _, filepath = indexed_filepaths[frame - 1]
                return filepath
            except IndexError as error:
                raise RuntimeError(
                    f'Frame {frame} in image sequence "{image.name}" '
                    "does not exist (contains only "
                    f'"{len(indexed_filepaths)}" frames)'
                ) from error

        if image.source == "TILED":
            # UDIM is not supported - export the active tile only.
            tile = image.tiles.active
            tile_path = image.filepath.replace("<UDIM>", str(tile.number))
            try:
                return utils.get_abspath(
                    tile_path, library=image.library,
                    must_exist=True, must_be_existing_file=True)
            except OSError as error:
                raise OSError(
                    f"Could not find UDIM tile {tile.number} of image "
                    f"'{image.name}' at path '{tile_path}' ({error})"
                ) from error

        # Unhandled source
        raise NotImplementedError(
            f"Unsupported image source '{image.source}' "
            f"in image '{image.name}'"
        )

    @classmethod
    def cycles_colorspace(cls, image, alpha=False, unassociate=False):
        """Blender의 이미지 입력 색 공간을 선형 작업 공간으로 전달한다."""
        if alpha or image.colorspace_settings.is_data:
            return {"colorspace": "nop"}
        override = os.environ.get("OCIO", "")
        config_path = override if os.path.isfile(override) else bpy.utils.system_resource(
            "DATAFILES", path="colormanagement/config.ocio")
        if not config_path or not os.path.isfile(config_path):
            raise OSError("Blender 이미지 입력의 OCIO 설정 파일을 찾을 수 없습니다")
        config_path = os.path.abspath(config_path)
        name = image.colorspace_settings.name
        key = (config_path, os.stat(config_path).st_mtime_ns)
        config = cls._cycles_ocio_configs.get(key)
        if config is None:
            if len(cls._cycles_ocio_configs) > 4:
                cls._cycles_ocio_configs.clear()
            config = ocio.Config.CreateFromFile(config_path)
            cls._cycles_ocio_configs[key] = config
        if config.getColorSpace(name) is None:
            raise OSError(f'OCIO 설정에 이미지 색 공간 "{name}"이 없습니다')
        return {"colorspace": "opencolorio", "colorspace.config": config_path,
                "colorspace.name": name, "storage": "float",
                "premultiplyalpha": image.alpha_mode == "STRAIGHT" and not unassociate,
                "unpremultiplyalpha": image.alpha_mode == "PREMUL" and unassociate}

    @classmethod
    def export_cycles_node_reader(cls, image):
        """Export cycles node reader."""
        # TODO deduplicate code, support image sequences
        cls.used_images.add(image)

        if image.source == "GENERATED":
            return cls._save_to_temp_file(image)

        if image.source == "FILE":
            if image.packed_file:
                return cls._save_to_temp_file(image)

            try:
                filepath = utils.get_abspath(
                    image.filepath,
                    library=image.library,
                    must_exist=True,
                    must_be_existing_file=True,
                )
                return filepath
            except OSError as error:
                # Make the error message more precise
                raise OSError(
                    f'Could not find image "{image.name}" '
                    f'at path "{image.filepath}" ({error})'
                ) from error

        if image.source == "TILED":
            # UDIM is not supported - export the active tile only.
            tile = image.tiles.active
            tile_path = image.filepath.replace("<UDIM>", str(tile.number))
            try:
                return utils.get_abspath(
                    tile_path, library=image.library,
                    must_exist=True, must_be_existing_file=True)
            except OSError as error:
                raise OSError(
                    f'Could not find UDIM tile {tile.number} of image '
                    f'"{image.name}" at path "{tile_path}" ({error})'
                ) from error

        raise NotImplementedError(
            f'Unsupported image source "{image.source}" '
            f'in image "{image.name}"'
        )

    @classmethod
    def free_blender_buffers(cls):
        """Release Blender-side decoded pixel buffers of exported images.

        Only file-backed, unmodified images are touched: their content
        is recoverable from disk (or the packed file), so freeing can
        never lose data. Generated/dirty images keep their pixels.
        """
        freed = 0
        for image in cls.used_images:
            try:
                if (
                    image.source in {"FILE", "SEQUENCE"}
                    and not image.is_dirty
                    and image.has_data
                ):
                    image.buffers_free()
                    image.gl_free()
                    freed += 1
            except Exception:
                # Image may have been removed or is otherwise not
                # freeable — never let this break a render
                pass
        if freed:
            print(
                f"[BLC] Freed Blender pixel buffers of {freed} image(s) "
                "for the duration of the render"
            )

    @classmethod
    def cleanup(cls):
        """Remove cached images."""
        for temp_image in cls.temp_images.values():
            filepath = temp_image.name
            temp_image.close()
            print("Deleting temporary image:", filepath)
            os.remove(filepath)

        cls.temp_images.clear()
        cls.used_images.clear()
