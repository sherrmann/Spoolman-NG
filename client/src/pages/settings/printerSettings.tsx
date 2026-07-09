import { PlusOutlined } from "@ant-design/icons";
import { useTranslate } from "@refinedev/core";
import { Button, Flex, Form, Input, Modal, Popconfirm, Table, message } from "antd";
import { useState } from "react";
import { Trans } from "react-i18next";
import {
  IPrinter,
  useCreatePrinter,
  useDeletePrinter,
  useGetPrinters,
  useUpdatePrinter,
} from "../../utils/queryPrinters";

// Printers (#75) are managed here rather than as a top-level nav resource, keeping the sidebar
// uncluttered. Spools are assigned to a printer from the spool form once at least one exists.
export function PrinterSettings() {
  const t = useTranslate();
  const printers = useGetPrinters();
  const createPrinter = useCreatePrinter();
  const updatePrinter = useUpdatePrinter();
  const deletePrinter = useDeletePrinter();

  const [form] = Form.useForm();
  const [editing, setEditing] = useState<IPrinter | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setIsOpen(true);
  };

  const openEdit = (printer: IPrinter) => {
    setEditing(printer);
    form.setFieldsValue({ name: printer.name, comment: printer.comment });
    setIsOpen(true);
  };

  const submit = async () => {
    let values: { name: string; comment?: string };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    try {
      if (editing) {
        await updatePrinter.mutateAsync({ id: editing.id, ...values });
      } else {
        await createPrinter.mutateAsync(values);
      }
      setIsOpen(false);
    } catch (e) {
      if (e instanceof Error) messageApi.error(e.message);
    }
  };

  const remove = async (printer: IPrinter) => {
    try {
      await deletePrinter.mutateAsync(printer.id);
    } catch (e) {
      if (e instanceof Error) messageApi.error(e.message);
    }
  };

  return (
    <>
      <Trans i18nKey="settings.printers.description" components={{ p: <p /> }} />
      <Table
        rowKey="id"
        dataSource={printers.data ?? []}
        loading={printers.isLoading}
        pagination={false}
        columns={[
          { title: t("printer.fields.name"), dataIndex: "name" },
          { title: t("printer.fields.comment"), dataIndex: "comment" },
          { title: t("printer.fields.spool_count"), dataIndex: "spool_count", width: "15%" },
          {
            title: "",
            width: "20%",
            render: (_, record: IPrinter) => (
              <Flex gap="small">
                <Button size="small" onClick={() => openEdit(record)}>
                  {t("buttons.edit")}
                </Button>
                <Popconfirm
                  title={t("settings.printers.delete_confirm", { name: record.name })}
                  onConfirm={() => remove(record)}
                  okText={t("buttons.delete")}
                  cancelText={t("buttons.cancel")}
                >
                  <Button size="small" danger>
                    {t("buttons.delete")}
                  </Button>
                </Popconfirm>
              </Flex>
            ),
          },
        ]}
      />
      <Flex justify="center">
        <Button
          type="primary"
          shape="circle"
          icon={<PlusOutlined />}
          size="large"
          style={{ margin: "1em" }}
          onClick={openCreate}
        />
      </Flex>
      <Modal
        open={isOpen}
        title={editing ? t("settings.printers.edit_title") : t("settings.printers.add_title")}
        onOk={submit}
        onCancel={() => setIsOpen(false)}
        confirmLoading={createPrinter.isPending || updatePrinter.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item label={t("printer.fields.name")} name="name" rules={[{ required: true, max: 64 }]}>
            <Input />
          </Form.Item>
          <Form.Item label={t("printer.fields.comment")} name="comment" rules={[{ max: 1024 }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
      {contextHolder}
    </>
  );
}
