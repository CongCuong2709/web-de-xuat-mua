// Phần JS nhỏ của app. Chạy trước Alpine (thứ tự defer), nên đăng ký component ở alpine:init.

// Form tạo/sửa đề xuất: danh sách món, tự tính tổng, báo trước có cần Chủ tịch duyệt.
document.addEventListener("alpine:init", () => {
  Alpine.data("proposalForm", (threshold) => {
    let seq = 0;
    const digits = (v) => Number(String(v || "").replace(/[^\d]/g, "")) || 0;
    const num = (v) => Number(String(v || "").replace(",", ".")) || 0;
    const raw = JSON.parse(document.getElementById("items-data").textContent);
    return {
      threshold,
      items: raw.map((r) => ({ key: ++seq, name: r.name, qty: r.qty || "1", price: r.price })),
      add() { this.items.push({ key: ++seq, name: "", qty: "1", price: "" }); },
      remove(i) { this.items.splice(i, 1); },
      step(it, d) { it.qty = String(Math.max(1, Math.round(num(it.qty) + d))); },
      line(it) { return Math.round(num(it.qty) * digits(it.price)); },
      get total() { return this.items.reduce((s, it) => s + (it.name.trim() ? this.line(it) : 0), 0); },
      fmt(n) { return n.toLocaleString("vi-VN"); },
    };
  });
});

// Trang Chờ tôi xử lý trên màn hình rộng: bấm thẻ thì mở chi tiết ở khung bên phải, không chuyển trang.
(function () {
  const paneVisible = () => {
    const pane = document.getElementById("pane");
    return pane && getComputedStyle(pane).display !== "none" ? pane : null;
  };
  const open = (link) => {
    document.querySelectorAll(".js-pane-link.is-selected").forEach((x) => x.classList.remove("is-selected"));
    link.classList.add("is-selected");
    htmx.ajax("GET", link.dataset.paneUrl, { target: "#pane", swap: "innerHTML" });
  };
  document.addEventListener("click", (e) => {
    const link = e.target.closest(".js-pane-link");
    if (!link || e.ctrlKey || e.metaKey || e.shiftKey || !paneVisible()) return;
    e.preventDefault();
    open(link);
  });
  document.addEventListener("DOMContentLoaded", () => {
    const first = document.querySelector(".js-pane-link");
    if (first && paneVisible()) open(first);
  });
})();
