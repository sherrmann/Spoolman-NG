import { CameraOutlined, SwapOutlined } from "@ant-design/icons";
import { useTranslate, useUpdate } from "@refinedev/core";
import { IDetectedBarcode, Scanner } from "@yudiel/react-qr-scanner";
import { Button, Modal, Segmented, Space, Typography, message } from "antd";
import { useRef, useState } from "react";
import { useNavigate } from "react-router";
import { parseScanResult } from "../utils/scan";
import { ScanAction, decideScan } from "../utils/scanMove";
import { getAPIURL } from "../utils/url";
import { ILocation } from "../pages/locations/model";

const { Text } = Typography;

/**
 * The QR scanning surface — camera view, scan handling and error messaging —
 * without any trigger button or modal chrome. Rendered inside the unified
 * ScanModal.
 *
 * Two actions (#84): "Open" navigates to the scanned resource (the original
 * behaviour); "Move spool" is a two-scan flow — scan a spool, then a destination
 * location, confirm, and the spool is moved there. The decision logic lives in
 * decideScan (unit-tested); this component only wires outcomes to effects. Scan
 * state is mirrored into refs so the per-frame onScan callback always reads the
 * latest values, never a stale closure.
 */
export const QRScannerPanel = ({ onClose }: { onClose?: () => void }) => {
  const [lastError, setLastError] = useState<string | null>(null);
  const [action, setAction] = useState<ScanAction>("open");
  const [moveSpoolId, setMoveSpoolId] = useState<number | null>(null);
  const t = useTranslate();
  const navigate = useNavigate();
  const [messageApi, contextHolder] = message.useMessage();
  const { mutate: updateSpool } = useUpdate();

  // Refs read by the per-frame onScan callback (avoids stale-closure reads between renders).
  const actionRef = useRef(action);
  actionRef.current = action;
  const spoolRef = useRef(moveSpoolId);
  spoolRef.current = moveSpoolId;
  // Guards the async propose→confirm→PATCH section so a burst of frames can't fire it twice.
  const processingRef = useRef(false);

  const setSpool = (id: number | null) => {
    spoolRef.current = id;
    setMoveSpoolId(id);
  };

  const onScan = async (detectedCodes: IDetectedBarcode[]) => {
    if (detectedCodes.length === 0) {
      return;
    }
    const target = parseScanResult(detectedCodes[0].rawValue);
    const outcome = decideScan(actionRef.current, spoolRef.current, target);

    if (outcome.kind === "navigate") {
      onClose?.();
      navigate(outcome.path);
    } else if (outcome.kind === "capture_spool") {
      setSpool(outcome.spoolId);
    } else if (outcome.kind === "propose_move") {
      if (processingRef.current) {
        return;
      }
      processingRef.current = true;
      try {
        const res = await fetch(`${getAPIURL()}/locations/${outcome.locationId}`);
        if (!res.ok) {
          throw new Error("load");
        }
        const loc = (await res.json()) as ILocation;
        Modal.confirm({
          title: t("scan.move.confirm_title"),
          content: t("scan.move.confirm_content", { spool: outcome.spoolId, location: loc.name }),
          okText: t("buttons.continue"),
          cancelText: t("buttons.cancel"),
          onOk: () => {
            updateSpool(
              {
                resource: "spool",
                id: outcome.spoolId,
                values: { location: loc.name },
                mutationMode: "pessimistic",
                successNotification: false,
              },
              {
                onSuccess: () => {
                  messageApi.success(t("scan.move.moved", { spool: outcome.spoolId, location: loc.name }));
                  setSpool(null);
                  processingRef.current = false;
                  onClose?.();
                },
                onError: () => {
                  processingRef.current = false;
                },
              },
            );
          },
          onCancel: () => {
            processingRef.current = false;
          },
        });
      } catch {
        messageApi.error(t("scan.move.load_error"));
        processingRef.current = false;
      }
    }
    // need_spool / need_location / ignore: no toast (would spam per frame); the hint text guides the user.
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {contextHolder}
      <Segmented
        block
        options={[
          { label: t("scan.action.open"), value: "open", icon: <CameraOutlined /> },
          { label: t("scan.action.move"), value: "move", icon: <SwapOutlined /> },
        ]}
        value={action}
        onChange={(value) => {
          setAction(value as ScanAction);
          setSpool(null);
        }}
      />
      {action === "move" &&
        (moveSpoolId === null ? (
          <Text type="secondary">{t("scan.move.scan_spool")}</Text>
        ) : (
          <Space>
            <Text>{t("scan.move.scan_location", { id: moveSpoolId })}</Text>
            <Button size="small" onClick={() => setSpool(null)}>
              {t("buttons.cancel")}
            </Button>
          </Space>
        ))}
      <p>{t("scanner.description")}</p>
      <Scanner
        constraints={{
          facingMode: "environment",
        }}
        onScan={onScan}
        // Accept common 2D matrix codes, not just QR, so labels generated with e.g.
        // Data Matrix or Aztec codes can be scanned too (issue #887). Payloads that
        // don't match the spoolman format are ignored, so widening this is harmless.
        formats={["qr_code", "micro_qr_code", "rm_qr_code", "data_matrix", "aztec", "pdf417"]}
        onError={(err: unknown) => {
          const error = err as Error;
          console.error(error);
          if (error.name === "NotAllowedError") {
            setLastError(t("scanner.error.notAllowed"));
          } else if (
            error.name === "InsecureContextError" ||
            (location.protocol !== "https:" && navigator.mediaDevices === undefined)
          ) {
            setLastError(t("scanner.error.insecureContext"));
          } else if (error.name === "StreamApiNotSupportedError") {
            setLastError(t("scanner.error.streamApiNotSupported"));
          } else if (error.name === "NotReadableError") {
            setLastError(t("scanner.error.notReadable"));
          } else if (error.name === "NotFoundError") {
            setLastError(t("scanner.error.notFound"));
          } else {
            setLastError(t("scanner.error.unknown", { error: error.name }));
          }
        }}
      >
        {lastError && (
          <div
            style={{
              position: "absolute",
              textAlign: "center",
              width: "100%",
              top: "50%",
            }}
          >
            <p>{lastError}</p>
          </div>
        )}
      </Scanner>
    </Space>
  );
};
