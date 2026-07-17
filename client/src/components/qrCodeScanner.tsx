import { CameraOutlined, SwapOutlined } from "@ant-design/icons";
import { useTranslate, useUpdate } from "@refinedev/core";
import { IDetectedBarcode, Scanner } from "@yudiel/react-qr-scanner";
import { Button, Modal, Segmented, Select, Space, Typography, message } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { apiFetch } from "../utils/authReloadHandler";
import { isClearScan, looksLikeRetailBarcode, parseScanResult } from "../utils/scan";
import { ScanAction, decideScan } from "../utils/scanMove";
import { useSavedState } from "../utils/saveload";
import { getAPIURL } from "../utils/url";
import { ILocation } from "../pages/locations/model";

// The barcode symbologies the camera will decode. Spoolman's own labels are QR/2D (#887); the retail
// 1D formats (#97b) let a manufacturer's UPC/EAN barcode drive an article-number lookup-or-create.
const SCAN_FORMATS = [
  "qr_code",
  "micro_qr_code",
  "rm_qr_code",
  "data_matrix",
  "aztec",
  "pdf417",
  "ean_13",
  "ean_8",
  "upc_a",
  "upc_e",
] as const;

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

  // #110: let the user pick and persist which camera feeds the scanner, instead of the browser
  // silently defaulting to whichever device (including virtual cameras) it granted first. Empty ""
  // means "let the browser choose the environment-facing camera" (today's behaviour).
  const [cameraId, setCameraId] = useSavedState<string>("scanner-camera-device", "");
  const [cameras, setCameras] = useState<MediaDeviceInfo[]>([]);
  useEffect(() => {
    const md = navigator.mediaDevices;
    if (!md?.enumerateDevices) {
      return undefined;
    }
    const refresh = () => {
      md.enumerateDevices()
        .then((all) => setCameras(all.filter((d) => d.kind === "videoinput")))
        .catch(() => {
          /* enumeration unavailable (e.g. permission not yet granted) */
        });
    };
    refresh();
    md.addEventListener?.("devicechange", refresh);
    return () => md.removeEventListener?.("devicechange", refresh);
  }, []);

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

  // #97b: an unrecognised retail barcode (UPC/EAN) becomes a lookup-or-create by article number.
  // A single match jumps to a prefilled spool-create; no match offers to create a filament that
  // remembers the barcode, so the next scan resolves. Guarded so a burst of frames fires it once.
  const handleRetailBarcode = async (code: string) => {
    if (processingRef.current) {
      return;
    }
    processingRef.current = true;
    try {
      // Quote the term so the article_number filter matches exactly, not as a substring.
      const url = `${getAPIURL()}/filament?article_number=${encodeURIComponent(`"${code}"`)}`;
      const res = await apiFetch(url);
      if (!res.ok) {
        throw new Error("lookup");
      }
      const filaments = (await res.json()) as { id: number }[];
      if (filaments.length > 0) {
        onClose?.();
        navigate(`/spool/create?filament_id=${filaments[0].id}`);
        return;
      }
      Modal.confirm({
        title: t("scan.barcode.unknown_title"),
        content: t("scan.barcode.unknown_content", { code }),
        okText: t("scan.barcode.create_filament"),
        cancelText: t("buttons.cancel"),
        onOk: () => {
          onClose?.();
          navigate(`/filament/create?article_number=${encodeURIComponent(code)}`);
        },
        onCancel: () => {
          processingRef.current = false;
        },
      });
    } catch {
      messageApi.error(t("scan.barcode.lookup_error"));
      processingRef.current = false;
    }
  };

  const onScan = async (detectedCodes: IDetectedBarcode[]) => {
    if (detectedCodes.length === 0) {
      return;
    }
    const raw = detectedCodes[0].rawValue;

    // #132: acknowledge the reserved clear-spool sentinel rather than silently ignoring it. Spoolman
    // has no active-spool state itself, so in-app this is just informational feedback.
    if (isClearScan(raw)) {
      messageApi.info(t("scan.clear.recognized"));
      onClose?.();
      return;
    }

    const target = parseScanResult(raw);

    // A retail-looking barcode that isn't a Spoolman code drives the article-number flow (open mode
    // only, so it never interferes with the two-scan move flow).
    if (target === null && actionRef.current === "open" && looksLikeRetailBarcode(raw)) {
      await handleRetailBarcode(raw);
      return;
    }

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
        const res = await apiFetch(`${getAPIURL()}/locations/${outcome.locationId}`);
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
      {cameras.length > 1 && (
        <Select
          value={cameraId}
          onChange={setCameraId}
          style={{ width: "100%" }}
          options={[
            { value: "", label: t("scanner.camera_auto") },
            ...cameras.map((cam, i) => ({
              value: cam.deviceId,
              label: cam.label || t("scanner.camera_n", { n: i + 1 }),
            })),
          ]}
        />
      )}
      <p>{t("scanner.description")}</p>
      <Scanner
        constraints={cameraId ? { deviceId: { exact: cameraId } } : { facingMode: "environment" }}
        onScan={onScan}
        formats={[...SCAN_FORMATS]}
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
