import { CameraOutlined, PictureOutlined, ScanOutlined, WifiOutlined } from "@ant-design/icons";
import loadable from "@loadable/component";
import { useTranslate } from "@refinedev/core";
import { FloatButton, Modal, Segmented, Space, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { useGetSettings } from "../utils/querySettings";
import { NfcScannerPanel, useNfcAvailability } from "./nfcScannerModal";
import { PhotoIntakePanel } from "./photoIntake";

const { Text } = Typography;

// The camera scanner stack behind QRScannerPanel (@yudiel/react-qr-scanner →
// barcode-detector, webrtc-adapter, sdp) is ~135 kB minified and is only needed once
// the scan modal is actually opened, so it must not be imported statically: this file
// sits in the always-loaded header chrome, and a static import would drag the whole
// stack into the eager entry chunk (#170). Loaded on first open, cached after that.
const QRScannerPanel = loadable<{ onClose?: () => void }, typeof import("./qrCodeScanner")>(
  () => import("./qrCodeScanner"),
  {
    resolveComponent: (mod) => mod.QRScannerPanel,
    fallback: (
      <div style={{ textAlign: "center", padding: 24 }}>
        <Spin />
      </div>
    ),
  },
);

/**
 * Unified "Scan" affordance for the global chrome. A single floating button opens
 * one modal that offers camera/QR scanning, plus an NFC option when server-side or
 * Web NFC scanning is available. On desktop browsers without Web NFC it is QR-only,
 * with a hint that NFC scanning needs Android Chrome. Both scanning surfaces are
 * composed from the existing scanner panels rather than reimplemented.
 */
const ScanModal = () => {
  const t = useTranslate();
  const [visible, setVisible] = useState(false);
  const [mode, setMode] = useState<"qr" | "nfc" | "photo">("qr");

  const { available: nfcAvailable } = useNfcAvailability();
  // Scan-to-Spool (#361): the Photo tab exists only while the feature is enabled —
  // invisible-unless-enabled, and no extra request (the settings query is app-wide).
  const settings = useGetSettings();
  const photoAvailable = settings.data?.ai_feature_scan_to_spool?.value === "true";

  // If a mode stops being available while the modal is open, fall back to QR.
  useEffect(() => {
    if ((!nfcAvailable && mode === "nfc") || (!photoAvailable && mode === "photo")) {
      setMode("qr");
    }
  }, [nfcAvailable, photoAvailable, mode]);

  const modeOptions = [
    { label: t("scan.qr"), value: "qr", icon: <CameraOutlined /> },
    ...(nfcAvailable ? [{ label: t("scan.nfc"), value: "nfc", icon: <WifiOutlined /> }] : []),
    ...(photoAvailable ? [{ label: t("scan.photo"), value: "photo", icon: <PictureOutlined /> }] : []),
  ];

  const close = () => setVisible(false);

  return (
    <>
      <FloatButton type="primary" onClick={() => setVisible(true)} icon={<ScanOutlined />} shape="circle" />
      <Modal open={visible} destroyOnHidden onCancel={close} footer={null} title={t("scan.title")}>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          {modeOptions.length > 1 ? (
            <Segmented
              block
              options={modeOptions}
              value={mode}
              onChange={(value) => setMode(value as "qr" | "nfc" | "photo")}
            />
          ) : (
            <Text type="secondary">{t("scan.nfc_hint")}</Text>
          )}
          {modeOptions.length > 1 && !nfcAvailable && <Text type="secondary">{t("scan.nfc_hint")}</Text>}
          {mode === "qr" && <QRScannerPanel onClose={close} />}
          {mode === "nfc" && nfcAvailable && <NfcScannerPanel active={visible && mode === "nfc"} onClose={close} />}
          {mode === "photo" && photoAvailable && <PhotoIntakePanel onClose={close} />}
        </Space>
      </Modal>
    </>
  );
};

export default ScanModal;
