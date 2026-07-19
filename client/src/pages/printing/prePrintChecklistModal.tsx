import { useTranslate } from "@refinedev/core";
import { Alert, Button, Checkbox, Modal } from "antd";
import { useState } from "react";

interface PrePrintChecklistModalProps {
  open: boolean;
  paperWidth: number;
  paperHeight: number;
  // The curated "Label …" paper sizes only print at true geometry when pageSizeMode is
  // "label"; the hint offers the one-click switch when it is still "auto".
  showPageSizeModeHint: boolean;
  onApplyPageSizeMode: () => void;
  onCancel: () => void;
  onConfirm: (dontShowAgain: boolean) => void;
}

// #296: the preview is geometrically exact, but the browser's print dialog can silently
// re-scale the page (fit-to-page), pick the wrong paper size, add driver margins or
// headers/footers — so a faithful preview still prints wrong. This checklist surfaces the
// checks at the moment they matter, between the Print button and the browser dialog.
const PrePrintChecklistModal = ({
  open,
  paperWidth,
  paperHeight,
  showPageSizeModeHint,
  onApplyPageSizeMode,
  onCancel,
  onConfirm,
}: PrePrintChecklistModalProps) => {
  const t = useTranslate();
  // Committed only on proceed, so cancelling never persists an accidental opt-out.
  const [dontShowAgain, setDontShowAgain] = useState(false);

  return (
    <Modal
      open={open}
      title={t("printing.generic.checklist.title")}
      onCancel={onCancel}
      footer={
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Checkbox
            checked={dontShowAgain}
            onChange={(e) => setDontShowAgain(e.target.checked)}
            style={{ marginRight: "auto" }}
          >
            {t("printing.generic.checklist.dontShowAgain")}
          </Checkbox>
          <Button onClick={onCancel}>{t("buttons.cancel")}</Button>
          <Button type="primary" onClick={() => onConfirm(dontShowAgain)}>
            {t("printing.generic.checklist.printNow")}
          </Button>
        </div>
      }
    >
      <p>{t("printing.generic.checklist.intro")}</p>
      <ul>
        <li>{t("printing.generic.checklist.scale")}</li>
        <li>{t("printing.generic.checklist.paperSize", { width: paperWidth, height: paperHeight })}</li>
        <li>{t("printing.generic.checklist.margins")}</li>
        <li>{t("printing.generic.checklist.headersFooters")}</li>
      </ul>
      {showPageSizeModeHint && (
        <Alert
          type="info"
          showIcon
          message={t("printing.generic.checklist.pageSizeModeHint")}
          action={
            <Button size="small" onClick={onApplyPageSizeMode}>
              {t("printing.generic.checklist.pageSizeModeApply")}
            </Button>
          }
        />
      )}
    </Modal>
  );
};

export default PrePrintChecklistModal;
