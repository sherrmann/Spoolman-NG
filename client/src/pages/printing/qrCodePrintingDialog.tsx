import { useTranslate } from "@refinedev/core";
import {
  Col,
  Form,
  Input,
  InputNumber,
  QRCode,
  Radio,
  RadioChangeEvent,
  Row,
  Select,
  Slider,
  Switch,
  Typography,
} from "antd";
import { ReactElement } from "react";
import { code128Bars } from "../../utils/barcode";
import { formatNumberOnUserInput, numberParser } from "../../utils/parsing";
import { getBasePath } from "../../utils/url";
import { DEFAULT_QR_SIZE_MM, MIN_SCANNABLE_QR_MM, qrContainerBasis } from "./labelLayout";
import { QRCodePrintSettings } from "./printing";
import PrintingDialog from "./printingDialog";

const { Text } = Typography;

// The filament colour to draw as a swatch (#114). A plain hex string for a single colour, or the
// multi-colour shape used elsewhere in the app (spoolIcon/filamentSelectModal).
export type SwatchColor = string | { colors: string[]; vertical: boolean };

interface QRCodeData {
  value: string;
  label?: ReactElement;
  errorLevel?: "L" | "M" | "Q" | "H";
  // Optional filament colour for the #114 swatch. Omitted ⇒ no swatch drawn for this item.
  color?: SwatchColor;
}

interface QRCodePrintingDialogProps {
  items: QRCodeData[];
  printSettings: QRCodePrintSettings;
  setPrintSettings: (setPrintSettings: QRCodePrintSettings) => void;
  extraSettings?: ReactElement;
  extraSettingsStart?: ReactElement;
  extraButtons?: ReactElement;
  baseUrlRoot: string;
  useHTTPUrl: boolean;
  setUseHTTPUrl: (value: boolean) => void;
  previewValues?: { default: string; url: string };
  onPrinted?: () => void;
}

// A small colored box for the label (#114). Single colour ⇒ one box; multi-colour ⇒ the same
// flex-stripe technique the spool icon uses, so coaxial/longitudinal filaments read correctly.
const LabelSwatch = ({ color, size }: { color?: SwatchColor; size: number }) => {
  if (!color) return null;
  const box: React.CSSProperties = {
    width: `${size}mm`,
    height: `${size}mm`,
    borderRadius: `${size * 0.15}mm`,
    overflow: "hidden",
    flex: "0 0 auto",
  };
  if (typeof color === "string") {
    return <div style={{ ...box, backgroundColor: "#" + color.replace("#", "") }} />;
  }
  return (
    <div style={{ ...box, display: "flex", flexDirection: color.vertical ? "column" : "row" }}>
      {color.colors.map((c, i) => (
        <div key={i} style={{ flex: "1 1 0", backgroundColor: "#" + c.replace("#", "") }} />
      ))}
    </div>
  );
};

// Render Code 128 module columns (#138) as an SVG that stretches to the available width. crispEdges
// keeps the bars sharp; preserveAspectRatio="none" lets a fixed module grid fill the label width.
const Barcode = ({ modules, heightMm }: { modules: boolean[]; heightMm: number }) => {
  const total = modules.length;
  const rects: ReactElement[] = [];
  let i = 0;
  while (i < total) {
    if (modules[i]) {
      let w = 1;
      while (i + w < total && modules[i + w]) w += 1;
      rects.push(<rect key={i} x={i} y={0} width={w} height={10} fill="#000" />);
      i += w;
    } else {
      i += 1;
    }
  }
  return (
    <svg
      className="print-qrcode-barcode"
      viewBox={`0 0 ${total} 10`}
      preserveAspectRatio="none"
      width="100%"
      height={`${heightMm}mm`}
      shapeRendering="crispEdges"
    >
      {rects}
    </svg>
  );
};

// Layer QR-specific controls on top of the shared sheet-printing dialog used by spool and filament labels.
const QRCodePrintingDialog = ({
  items,
  printSettings,
  setPrintSettings,
  extraSettings,
  extraSettingsStart,
  extraButtons,
  baseUrlRoot,
  useHTTPUrl,
  setUseHTTPUrl,
  previewValues,
  onPrinted,
}: QRCodePrintingDialogProps) => {
  const t = useTranslate();

  const showContent = printSettings?.showContent === undefined ? true : printSettings?.showContent;
  const showQRCodeMode = printSettings?.showQRCodeMode || "withIcon";
  const textSize = printSettings?.textSize || 3;
  const qrPadding = printSettings?.qrPadding ?? 2;
  // Printed QR square in mm (#295). undefined ⇒ auto (fill), the only behavior before the setting existed.
  const qrSize = printSettings?.qrSize;
  // New optional layout/output settings — each defaults to the previous behavior (#106/#114/#79/#133/#138).
  const qrErrorLevel = printSettings?.qrErrorLevel ?? "H";
  const showColorSwatch = printSettings?.showColorSwatch ?? false;
  const qrPlacement = printSettings?.qrPlacement ?? "left";
  const textColumns = printSettings?.textColumns ?? 1;
  const barcode1d = printSettings?.barcode1d ?? "none";
  const preview = previewValues ?? ({ default: `WEB+SPOOLMAN:S-{id}`, url: `${baseUrlRoot}/spool/show/{id}` } as const);

  // The side content area shows when there is anything to put beside/under the QR: text, a swatch or a barcode.
  const showSide = showContent || showColorSwatch || barcode1d !== "none";

  // Build the printable QR blocks here; the underlying dialog handles page layout and export mechanics.
  const elements = items.map((item, idx) => {
    const barcodeModules = barcode1d === "code128" ? code128Bars(item.value) : null;
    return (
      <div className="print-qrcode-item" key={idx}>
        {showQRCodeMode !== "no" && (
          <div className="print-qrcode-container">
            <QRCode
              className="print-qrcode"
              icon={showQRCodeMode === "withIcon" ? getBasePath() + "/favicon.svg" : undefined}
              value={item.value}
              errorLevel={item.errorLevel ?? qrErrorLevel}
              type="svg"
              color="#000"
            />
          </div>
        )}
        {showSide && (
          <div className="print-qrcode-title" style={showQRCodeMode === "no" ? { paddingLeft: "1mm" } : {}}>
            {showColorSwatch && (
              <div className="print-qrcode-swatch">
                <LabelSwatch color={item.color} size={textSize} />
              </div>
            )}
            {showContent && (
              <div className="print-qrcode-text" style={textColumns > 1 ? { columnCount: textColumns } : undefined}>
                {item.label ?? item.value}
              </div>
            )}
            {barcodeModules && barcodeModules.length > 0 && (
              <Barcode modules={barcodeModules} heightMm={Math.max(textSize * 1.5, 4)} />
            )}
          </div>
        )}
      </div>
    );
  });

  // Flex direction encodes QR placement (#79): row = beside the text (default), column = above,
  // column-reverse = below. The container basis becomes a vertical split for the stacked layouts.
  const itemFlexDirection = qrPlacement === "top" ? "column" : qrPlacement === "bottom" ? "column-reverse" : "row";
  const containerBasis = qrContainerBasis({ showSide, qrSize, qrPadding });
  const qrTooSmall = qrSize !== undefined && qrSize < MIN_SCANNABLE_QR_MM && showQRCodeMode !== "no";

  return (
    <PrintingDialog
      items={elements}
      printSettings={printSettings.printSettings}
      setPrintSettings={(newSettings) => {
        // Spread to preserve immutability — printSettings.printSettings is a nested object
        setPrintSettings({ ...printSettings, printSettings: newSettings });
      }}
      extraButtons={extraButtons}
      extraSettingsStart={extraSettingsStart}
      onPrinted={onPrinted}
      extraSettings={
        <>
          <Form.Item label={t("printing.qrcode.showQRCode")}>
            <Radio.Group
              options={[
                { label: t("printing.qrcode.showQRCodeMode.no"), value: "no" },
                {
                  label: t("printing.qrcode.showQRCodeMode.simple"),
                  value: "simple",
                },
                { label: t("printing.qrcode.showQRCodeMode.withIcon"), value: "withIcon" },
              ]}
              onChange={(e: RadioChangeEvent) => {
                setPrintSettings({ ...printSettings, showQRCodeMode: e.target.value });
              }}
              value={showQRCodeMode}
              optionType="button"
              buttonStyle="solid"
            />
          </Form.Item>
          {showQRCodeMode !== "no" && (
            <>
              <Form.Item
                label={t("printing.qrcode.useHTTPUrl.label")}
                tooltip={t("printing.qrcode.useHTTPUrl.tooltip")}
                style={{ marginBottom: 0 }}
              >
                <Radio.Group onChange={(e) => setUseHTTPUrl(e.target.value)} value={useHTTPUrl}>
                  <Radio value={false}>{t("printing.qrcode.useHTTPUrl.options.default")}</Radio>
                  <Radio value={true}>{t("printing.qrcode.useHTTPUrl.options.url")}</Radio>
                </Radio.Group>
              </Form.Item>
              <Form.Item label={t("printing.qrcode.useHTTPUrl.preview")}>
                {/* Mirror the encoded payload so users can confirm which QR format the preset will emit. */}
                <Text> {printSettings?.customQrPayload || (useHTTPUrl ? preview.url : preview.default)}</Text>
              </Form.Item>
              <Form.Item
                label={t("printing.qrcode.customPayload.label")}
                tooltip={t("printing.qrcode.customPayload.tooltip")}
              >
                <Input
                  value={printSettings?.customQrPayload ?? ""}
                  placeholder={preview.default}
                  onChange={(e) => {
                    setPrintSettings({ ...printSettings, customQrPayload: e.target.value || undefined });
                  }}
                />
              </Form.Item>
              <Form.Item
                label={t("printing.qrcode.qrErrorLevel.label")}
                tooltip={t("printing.qrcode.qrErrorLevel.tooltip")}
              >
                <Radio.Group
                  options={[
                    { label: "L", value: "L" },
                    { label: "M", value: "M" },
                    { label: "Q", value: "Q" },
                    { label: "H", value: "H" },
                  ]}
                  onChange={(e: RadioChangeEvent) => {
                    setPrintSettings({ ...printSettings, qrErrorLevel: e.target.value });
                  }}
                  value={qrErrorLevel}
                  optionType="button"
                  buttonStyle="solid"
                />
              </Form.Item>
            </>
          )}
          <Form.Item label={t("printing.qrcode.showContent")}>
            <Switch
              checked={showContent}
              onChange={(checked) => {
                setPrintSettings({ ...printSettings, showContent: checked });
              }}
            />
          </Form.Item>
          {showQRCodeMode !== "no" && showSide && (
            <Form.Item
              label={t("printing.qrcode.qrPlacement.label")}
              tooltip={t("printing.qrcode.qrPlacement.tooltip")}
            >
              <Radio.Group
                options={[
                  { label: t("printing.qrcode.qrPlacement.left"), value: "left" },
                  { label: t("printing.qrcode.qrPlacement.top"), value: "top" },
                  { label: t("printing.qrcode.qrPlacement.bottom"), value: "bottom" },
                ]}
                onChange={(e: RadioChangeEvent) => {
                  setPrintSettings({ ...printSettings, qrPlacement: e.target.value });
                }}
                value={qrPlacement}
                optionType="button"
                buttonStyle="solid"
              />
            </Form.Item>
          )}
          <Form.Item
            label={t("printing.qrcode.showColorSwatch.label")}
            tooltip={t("printing.qrcode.showColorSwatch.tooltip")}
          >
            <Switch
              checked={showColorSwatch}
              onChange={(checked) => {
                setPrintSettings({ ...printSettings, showColorSwatch: checked });
              }}
            />
          </Form.Item>
          <Form.Item label={t("printing.qrcode.barcode1d.label")} tooltip={t("printing.qrcode.barcode1d.tooltip")}>
            <Select
              value={barcode1d}
              onChange={(value) => {
                setPrintSettings({ ...printSettings, barcode1d: value });
              }}
              options={[
                { label: t("printing.qrcode.barcode1d.none"), value: "none" },
                { label: t("printing.qrcode.barcode1d.code128"), value: "code128" },
              ]}
            />
          </Form.Item>
          <Form.Item label={t("printing.qrcode.textSize")}>
            <Row>
              <Col span={12}>
                <Slider
                  disabled={!showContent}
                  tooltip={{ formatter: (value) => `${value} mm` }}
                  min={2}
                  max={7}
                  value={textSize}
                  step={0.1}
                  onChange={(value) => {
                    setPrintSettings({ ...printSettings, textSize: value });
                  }}
                />
              </Col>
              <Col span={12}>
                <InputNumber
                  disabled={!showContent}
                  min={0.01}
                  step={0.1}
                  style={{ margin: "0 16px" }}
                  value={textSize}
                  addonAfter="mm"
                  formatter={formatNumberOnUserInput}
                  parser={numberParser}
                  onChange={(value) => {
                    setPrintSettings({ ...printSettings, textSize: value ?? 5 });
                  }}
                />
              </Col>
            </Row>
          </Form.Item>
          <Form.Item label={t("printing.qrcode.textColumns.label")} tooltip={t("printing.qrcode.textColumns.tooltip")}>
            <InputNumber
              disabled={!showContent}
              min={1}
              max={4}
              step={1}
              value={textColumns}
              onChange={(value) => {
                setPrintSettings({ ...printSettings, textColumns: value ?? 1 });
              }}
            />
          </Form.Item>
          <Form.Item
            label={t("printing.qrcode.qrSize.label")}
            tooltip={t("printing.qrcode.qrSize.tooltip")}
            validateStatus={qrTooSmall ? "warning" : undefined}
            help={qrTooSmall ? t("printing.qrcode.qrSize.tooSmall", { mm: MIN_SCANNABLE_QR_MM }) : undefined}
          >
            <Radio.Group
              disabled={showQRCodeMode === "no"}
              options={[
                { label: t("printing.qrcode.qrSize.auto"), value: "auto" },
                { label: t("printing.qrcode.qrSize.custom"), value: "custom" },
              ]}
              onChange={(e: RadioChangeEvent) => {
                setPrintSettings({
                  ...printSettings,
                  qrSize: e.target.value === "auto" ? undefined : DEFAULT_QR_SIZE_MM,
                });
              }}
              value={qrSize === undefined ? "auto" : "custom"}
              optionType="button"
              buttonStyle="solid"
            />
            {qrSize !== undefined && (
              <Row>
                <Col span={12}>
                  <Slider
                    disabled={showQRCodeMode === "no"}
                    tooltip={{ formatter: (value) => `${value} mm` }}
                    min={5}
                    max={50}
                    value={qrSize}
                    step={0.5}
                    onChange={(value) => {
                      setPrintSettings({ ...printSettings, qrSize: value });
                    }}
                  />
                </Col>
                <Col span={12}>
                  <InputNumber
                    disabled={showQRCodeMode === "no"}
                    min={1}
                    step={0.5}
                    style={{ margin: "0 16px" }}
                    value={qrSize}
                    addonAfter="mm"
                    formatter={formatNumberOnUserInput}
                    parser={numberParser}
                    onChange={(value) => {
                      // A cleared field falls back to the default; a typed 0 would silently
                      // mean "auto" in the layout while the control still shows Custom.
                      setPrintSettings({ ...printSettings, qrSize: value && value > 0 ? value : DEFAULT_QR_SIZE_MM });
                    }}
                  />
                </Col>
              </Row>
            )}
          </Form.Item>
          <Form.Item label={t("printing.qrcode.qrPadding")}>
            <Row>
              <Col span={12}>
                <Slider
                  disabled={showQRCodeMode === "no"}
                  tooltip={{ formatter: (value) => `${value} mm` }}
                  min={0}
                  max={5}
                  value={qrPadding}
                  step={0.1}
                  onChange={(value) => {
                    setPrintSettings({ ...printSettings, qrPadding: value });
                  }}
                />
              </Col>
              <Col span={12}>
                <InputNumber
                  disabled={showQRCodeMode === "no"}
                  min={0}
                  step={0.1}
                  style={{ margin: "0 16px" }}
                  value={qrPadding}
                  addonAfter="mm"
                  formatter={formatNumberOnUserInput}
                  parser={numberParser}
                  onChange={(value) => {
                    setPrintSettings({ ...printSettings, qrPadding: value ?? 2 });
                  }}
                />
              </Col>
            </Row>
          </Form.Item>

          {extraSettings}
        </>
      }
      style={`
            .print-page .print-qrcode-item {
              display: flex;
              flex-direction: ${itemFlexDirection};
              width: 100%;
              height: 100%;
              justify-content: center;
            }

            .print-page .print-qrcode-container {
              /* Definite basis that neither grows nor shrinks, so the QR renders at a consistent
                 size regardless of the label text length (#59). min-width/height 0 drop the flex
                 auto-minimum: without it the SVG's intrinsic size (160px) floors the container and
                 silently overrides both a custom mm size and the 50% split on narrow labels (#295). */
              flex: 0 0 ${containerBasis};
              display: flex;
              justify-content: center;
              align-items: center;
              min-width: 0;
              min-height: 0;
            }

            .print-page .print-qrcode {
              /* Fill the container (!important beats antd's inline 160px size) so the svg's
                 percentage size resolves against a definite box on both axes — with auto
                 sizing the svg fell back to its intrinsic 160px and overflowed the stacked
                 (top/bottom) layouts (#295). */
              width: 100% !important;
              height: 100% !important;
              padding: ${qrPadding}mm;
              min-width: 0;
              min-height: 0;
            }

            .print-page .print-qrcode-title {
              flex: 1 1 auto;
              display: flex;
              flex-direction: column;
              justify-content: center;
              gap: 1mm;
              font-size: ${textSize}mm;
              color: #000;
              overflow: hidden;
            }

            .print-page .print-qrcode-text {
              white-space: pre-wrap;
              overflow: hidden;
            }

            .print-page .print-qrcode-barcode {
              display: block;
            }

            .print-page canvas, .print-page .print-qrcode svg {
              /* The antd QRCode class sits on the wrapper div, so the old svg.print-qrcode
                 selector never matched: the svg kept its fixed 160px attributes and column
                 (top/bottom) placements drew it at 42mm regardless of the size setting (#295).
                 The descendant selector makes the svg genuinely track its box on both axes;
                 the square viewBox then letterboxes the QR to min(width, height). */
              object-fit: contain;
              height: 100% !important;
              width: 100% !important;
              max-height: 100%;
              max-width: 100%;
            }
            `}
    />
  );
};

export default QRCodePrintingDialog;
