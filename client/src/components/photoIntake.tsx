import { PictureOutlined } from "@ant-design/icons";
import { useTranslate } from "@refinedev/core";
import { Alert, Button, Descriptions, Radio, Space, Spin, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { SpoolIntakeExtraction, SpoolIntakeResult, useSpoolIntakeExtract } from "../utils/queryAI";

const { Text } = Typography;

// Scan-to-Spool capture + review (#361). The photo is downscaled client-side, sent as
// base64, analyzed, and then discarded — nothing is stored on either end. Matching is
// library-first: a known filament just gains a spool; a SpoolmanDB match lands on the
// spool form with the external filament preselected (the form creates both).

const MAX_EDGE = 1568;
const JPEG_QUALITY = 0.85;
const THUMB_EDGE = 120;

// The preview is returned as a Blob and rendered by drawing onto a <canvas>: no string
// derived from the user-selected file ever reaches a DOM attribute, which is what CodeQL
// js/xss-through-dom flags (it taints even URL.createObjectURL output via the File).
export async function fileToJpegBase64(file: File): Promise<{ base64: string; previewBlob: Blob }> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no canvas context");
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob: Blob = await new Promise((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode failed"))), "image/jpeg", JPEG_QUALITY),
    );
    return { base64: await blobToBase64(blob), previewBlob: blob };
  } catch {
    // Downscaling is an optimization; fall back to sending the original file.
    return { base64: await blobToBase64(file), previewBlob: file };
  }
}

async function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",", 2)[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** Build the create-form URL for a review choice ("lib:<id>", "cat:<external id>" or "raw"). */
export function buildHandoffUrl(choice: string, extraction: SpoolIntakeExtraction): string {
  const params = new URLSearchParams({ from_scan: "1" });
  if (choice.startsWith("lib:") || choice.startsWith("cat:")) {
    // Library ids are numeric; catalog handoff preselects the external filament by its
    // string id — the spool form then creates filament + spool in one save.
    params.set("filament_id", choice.slice(4));
    if (extraction.lot_nr) params.set("lot_nr", extraction.lot_nr);
    return `/spool/create?${params.toString()}`;
  }
  const fields: Record<string, string | number | null> = {
    name: extraction.name,
    material: extraction.material,
    weight: extraction.weight_g,
    spool_weight: extraction.spool_weight_g,
    extruder_temp: extraction.extruder_temp_c,
    bed_temp: extraction.bed_temp_c,
    color_hex: extraction.color_hex,
    article_number: extraction.article_number,
  };
  for (const [key, value] of Object.entries(fields)) {
    if (value !== null && value !== undefined) params.set(key, String(value));
  }
  return `/filament/create?${params.toString()}`;
}

const EXTRACTION_ROWS: { key: keyof SpoolIntakeExtraction; labelKey: string }[] = [
  { key: "vendor", labelKey: "intake.fields.vendor" },
  { key: "name", labelKey: "intake.fields.name" },
  { key: "material", labelKey: "intake.fields.material" },
  { key: "weight_g", labelKey: "intake.fields.weight_g" },
  { key: "diameter_mm", labelKey: "intake.fields.diameter_mm" },
  { key: "extruder_temp_c", labelKey: "intake.fields.extruder_temp_c" },
  { key: "bed_temp_c", labelKey: "intake.fields.bed_temp_c" },
  { key: "lot_nr", labelKey: "intake.fields.lot_nr" },
  { key: "article_number", labelKey: "intake.fields.article_number" },
  { key: "confidence", labelKey: "intake.fields.confidence" },
];

/** Photo thumbnail drawn onto a canvas. Decorative: stays collapsed (0 x 0) when the
 * browser lacks createImageBitmap or decoding fails, and the review works without it. */
function PreviewThumb(props: { blob: Blob }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const bitmap = await createImageBitmap(props.blob);
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;
        const scale = Math.min(1, THUMB_EDGE / Math.max(bitmap.width, bitmap.height));
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      } catch {
        // No preview, no problem — the extraction fields are the content that matters.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [props.blob]);
  return <canvas ref={canvasRef} width={0} height={0} style={{ borderRadius: 4 }} data-testid="intake-preview" />;
}

export function IntakeReview(props: {
  result: SpoolIntakeResult;
  previewBlob: Blob | null;
  onNavigate: (url: string) => void;
  onBack: () => void;
}) {
  const t = useTranslate();
  const { extraction, matches } = props.result;
  const options = [
    ...matches.library.map((match) => ({
      value: `lib:${match.filament_id}`,
      label: `${match.vendor ?? ""} ${match.name ?? ""} (${match.material ?? "?"}) - ${match.match_percent}% - ${t(
        "intake.in_library",
      )}`,
    })),
    ...matches.catalog.map((match) => ({
      value: `cat:${match.external_id}`,
      label: `${match.vendor ?? ""} ${match.name ?? ""} (${match.material ?? "?"}) - ${match.match_percent}% - ${t(
        "intake.from_catalog",
      )}`,
    })),
    { value: "raw", label: t("intake.use_raw") },
  ];
  const [choice, setChoice] = useState<string>(options[0].value);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }} data-testid="intake-review">
      <Space align="start" size="middle">
        {props.previewBlob && <PreviewThumb blob={props.previewBlob} />}
        <Descriptions size="small" column={1} style={{ maxWidth: 360 }}>
          {EXTRACTION_ROWS.filter((row) => extraction[row.key] !== null).map((row) => (
            <Descriptions.Item key={row.key} label={t(row.labelKey)}>
              {String(extraction[row.key])}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </Space>
      <Radio.Group
        value={choice}
        onChange={(event) => setChoice(event.target.value)}
        options={options}
        style={{ display: "flex", flexDirection: "column", gap: 8 }}
        data-testid="intake-choices"
      />
      <Text type="secondary">{t("intake.photo_discarded")}</Text>
      <Space>
        <Button onClick={props.onBack}>{t("intake.back")}</Button>
        <Button
          type="primary"
          onClick={() => props.onNavigate(buildHandoffUrl(choice, extraction))}
          data-testid="intake-continue"
        >
          {t("intake.continue")}
        </Button>
      </Space>
    </Space>
  );
}

export function PhotoIntakePanel(props: { onClose: () => void }) {
  const t = useTranslate();
  const navigate = useNavigate();
  const extract = useSpoolIntakeExtract();
  const inputRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<"pick" | "extracting" | "review">("pick");
  const [error, setError] = useState<string | null>(null);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [result, setResult] = useState<SpoolIntakeResult | null>(null);

  const onFile = async (file: File) => {
    setError(null);
    setPhase("extracting");
    try {
      const { base64, previewBlob: preview } = await fileToJpegBase64(file);
      setPreviewBlob(preview);
      const extracted = await extract.mutateAsync({ image_base64: base64, mime: "image/jpeg" });
      setResult(extracted);
      setPhase("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("pick");
    }
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {error && <Alert type="error" showIcon message={error} />}
      {phase === "pick" && (
        <div style={{ textAlign: "center", padding: 16 }}>
          <Space direction="vertical" size="middle">
            <Text type="secondary">{t("intake.hint")}</Text>
            <Button
              type="primary"
              icon={<PictureOutlined />}
              onClick={() => inputRef.current?.click()}
              data-testid="intake-pick"
            >
              {t("intake.select_photo")}
            </Button>
          </Space>
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            data-testid="intake-file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void onFile(file);
              event.target.value = "";
            }}
          />
        </div>
      )}
      {phase === "extracting" && (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Space direction="vertical">
            <Spin />
            <Text type="secondary">{t("intake.extracting")}</Text>
          </Space>
        </div>
      )}
      {phase === "review" && result && (
        <IntakeReview
          result={result}
          previewBlob={previewBlob}
          onBack={() => setPhase("pick")}
          onNavigate={(url) => {
            props.onClose();
            navigate(url);
          }}
        />
      )}
    </Space>
  );
}
