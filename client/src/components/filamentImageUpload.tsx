import { DeleteOutlined, PictureOutlined } from "@ant-design/icons";
import { useTranslate } from "@refinedev/core";
import { Button, Space, Upload, message } from "antd";
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../utils/authReloadHandler";
import { PreparedImage, prepareImageForUpload } from "../utils/imageTransform";
import { filamentImageUrl, invalidateEntityImage, useEntityImage } from "./entityImage";

// Reference-photo upload widgets for the filament forms (#88). The photo is not part of the form
// payload — it travels over its own PUT/DELETE endpoints — so neither widget registers a form
// field. Edit talks to the server directly; Create stages the prepared photo locally and the page
// uploads it after the POST has produced an id.

const PREVIEW_SIZE = 160;

const previewStyle: React.CSSProperties = {
  maxWidth: PREVIEW_SIZE * 2,
  maxHeight: PREVIEW_SIZE,
  borderRadius: 8,
  objectFit: "contain",
};

/** PUT a prepared photo to a filament, dropping any cached copy so views refetch. */
export async function uploadFilamentImage(filamentId: number, image: PreparedImage): Promise<void> {
  const url = filamentImageUrl(filamentId);
  const response = await apiFetch(url, {
    method: "PUT",
    body: image.blob,
    headers: { "Content-Type": image.contentType },
  });
  if (!response.ok) {
    throw new Error(`Image upload failed (HTTP ${response.status})`);
  }
  invalidateEntityImage(url);
}

/** DELETE the photo of a filament; a 404 (already gone) counts as success. */
export async function deleteFilamentImage(filamentId: number): Promise<void> {
  const url = filamentImageUrl(filamentId);
  const response = await apiFetch(url, { method: "DELETE" });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Image delete failed (HTTP ${response.status})`);
  }
  invalidateEntityImage(url);
}

/** Shared select-a-photo button; runs the downscale before handing the result to the caller. */
function SelectImageButton({
  label,
  busy,
  onPrepared,
}: {
  label: string;
  busy: boolean;
  onPrepared: (image: PreparedImage) => void;
}) {
  const t = useTranslate();
  return (
    <Upload
      accept="image/*"
      showUploadList={false}
      beforeUpload={(file) => {
        prepareImageForUpload(file)
          .then(onPrepared)
          .catch((error) => {
            console.error(error);
            message.error(t("filament.image.prepare_error"));
          });
        return false; // The prepared blob goes through our own PUT, not Upload's transport.
      }}
    >
      <Button icon={<PictureOutlined />} loading={busy}>
        {label}
      </Button>
    </Upload>
  );
}

/**
 * Photo section for the EDIT form: shows the current photo and uploads/removes immediately via the
 * image endpoints. `hasImage` seeds the state from the record; afterwards the section tracks its
 * own actions, since the form record only refreshes on save.
 */
export function FilamentImageSection({ filamentId, hasImage }: { filamentId?: number; hasImage?: boolean }) {
  const t = useTranslate();
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const [present, setPresent] = useState<boolean | null>(null);
  const showImage = present ?? !!hasImage;
  const src = useEntityImage(filamentId !== undefined && showImage ? filamentImageUrl(filamentId) : null, version);

  if (filamentId === undefined) {
    return null;
  }

  const upload = async (image: PreparedImage) => {
    setBusy(true);
    try {
      await uploadFilamentImage(filamentId, image);
      setPresent(true);
      setVersion((v) => v + 1);
      message.success(t("filament.image.uploaded"));
    } catch (error) {
      console.error(error);
      message.error(t("filament.image.upload_error"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deleteFilamentImage(filamentId);
      setPresent(false);
      message.success(t("filament.image.removed"));
    } catch (error) {
      console.error(error);
      message.error(t("filament.image.remove_error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Space direction="vertical">
      {showImage && src && <img src={src} alt={t("filament.fields.image")} style={previewStyle} />}
      <Space wrap>
        <SelectImageButton
          label={showImage ? t("filament.image.replace") : t("filament.image.upload")}
          busy={busy}
          onPrepared={(image) => void upload(image)}
        />
        {showImage && (
          <Button icon={<DeleteOutlined />} danger loading={busy} onClick={() => void remove()}>
            {t("filament.image.remove")}
          </Button>
        )}
      </Space>
    </Space>
  );
}

/**
 * Photo picker for the CREATE form: there is no filament id yet, so the prepared photo is staged
 * in the parent's state (`value`/`onChange`) and PUT by the page right after the POST succeeds.
 */
export function FilamentImagePicker({
  value,
  onChange,
}: {
  value: PreparedImage | null;
  onChange: (image: PreparedImage | null) => void;
}) {
  const t = useTranslate();
  const previewUrl = useMemo(() => (value ? URL.createObjectURL(value.blob) : null), [value]);
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  return (
    <Space direction="vertical">
      {previewUrl && <img src={previewUrl} alt={t("filament.fields.image")} style={previewStyle} />}
      <Space wrap>
        <SelectImageButton
          label={value ? t("filament.image.replace") : t("filament.image.upload")}
          busy={false}
          onPrepared={onChange}
        />
        {value && (
          <Button icon={<DeleteOutlined />} danger onClick={() => onChange(null)}>
            {t("filament.image.remove")}
          </Button>
        )}
      </Space>
    </Space>
  );
}
