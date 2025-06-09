// scrap2.js (no proxy version)
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const { parse } = require('json2csv');
const dayjs = require('dayjs');

const TARGET_URL = "https://nationalthaiwater.onwr.go.th/waterlevel";
const OUTPUT_FILE = "waterlevel_report.csv";

(async () => {
  let success = false;

  console.log(`🌐 เปิดหน้าเว็บแบบไม่ใช้ proxy`);
  try {
    const browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();

    await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 60000 });
    console.log(`📄 Title: ${await page.title()}`);
    console.log(`🌐 URL: ${page.url()}`);

    // ลองคลิกปุ่มคุกกี้ถ้ามี
    try {
      await page.click("button:contains('ยอมรับ')");
      console.log("✅ กดปุ่มคุกกี้แล้ว");
    } catch (e) {
      console.log("ℹ️ ไม่มีปุ่มคุกกี้หรือคลิกไม่ได้");
    }

    // รอให้ตารางโหลด
    try {
      console.log("⏳ รอตารางแสดงผลสูงสุด 60 วินาที...");
      await page.waitForSelector(".MuiTable-root tbody tr", { timeout: 60000 });
    } catch (e) {
      console.log("❌ ไม่พบตารางภายใน 60 วินาที → เขียน debug_page.html และ screenshot");
      fs.writeFileSync("debug_page.html", await page.content());
      await page.screenshot({ path: "debug_screenshot.png", fullPage: true });
      await browser.close();
      return;
    }

    const rows = await page.$$(".MuiTable-root tbody tr");
    const allData = [];
    for (let row of rows) {
      const cols = await row.$$eval("td", tds => tds.map(td => td.innerText.trim()));
      if (cols.length >= 5) {
        if (cols.length === 9) cols[8] = dayjs().format('DD/MM/YYYY');
        else cols.push(dayjs().format('DD/MM/YYYY'));
        allData.push(cols);
      }
    }

    await browser.close();

    if (allData.length) {
      const columnNames = [
        "ชื่อสถานี", "ที่ตั้ง", "เวลา", "ระดับน้ำ",
        "ระดับตลิ่ง", "ค่าศูนย์เสาระดับ", "%ความจุน้ำ",
        "สถานการณ์", "วันที่เก็บข้อมูล"
      ];
      const csv = parse(allData.map(row => Object.fromEntries(row.map((val, idx) => [columnNames[idx] || `เพิ่มเติม_${idx}`, val]))));

      fs.writeFileSync(OUTPUT_FILE, csv, { encoding: 'utf-8' });
      console.log(`✅ บันทึกข้อมูลสำเร็จที่ ${OUTPUT_FILE}`);
    } else {
      console.log("⚠️ ตารางโหลดแล้ว แต่ไม่มีข้อมูลแสดง");
      fs.writeFileSync(OUTPUT_FILE, "ข้อความ,ไม่มีข้อมูลให้บันทึก\n", { encoding: 'utf-8' });
    }

  } catch (err) {
    console.log(`❌ ล้มเหลว: ${err.message}`);
    if (!fs.existsSync(OUTPUT_FILE)) {
      fs.writeFileSync(OUTPUT_FILE, "ข้อความ,ไม่มีข้อมูลให้บันทึก\n", { encoding: 'utf-8' });
    }
  }
})();
