const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        AlignmentType, LevelFormat, ExternalHyperlink,
        BorderStyle, WidthType, ShadingType } = require('docx');

// Word-native bullet glyphs: level 0 = Symbol dot, level 1 = Courier New "o"
const doc = new Document({
    styles: {
        default: {
            document: { run: { font: "Calibri", size: 22 } }
        }
    },
    numbering: {
        config: [{
            reference: "bullets",
            levels: [
                {
                    level: 0,
                    format: LevelFormat.BULLET,
                    text: "\uF0B7",
                    alignment: AlignmentType.LEFT,
                    style: {
                        run: { font: "Symbol" },
                        paragraph: { indent: { left: 720, hanging: 360 } }
                    }
                },
                {
                    level: 1,
                    format: LevelFormat.BULLET,
                    text: "o",
                    alignment: AlignmentType.LEFT,
                    style: {
                        run: { font: "Courier New" },
                        paragraph: { indent: { left: 1440, hanging: 360 } }
                    }
                }
            ]
        }]
    },
    sections: [{
        properties: {
            page: {
                size: { width: 12240, height: 15840 },
                margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
            }
        },
        children: []
    }]
});

function t(text, opts = {}) {
    return new TextRun(Object.assign({ text, font: "Calibri", size: 22 }, opts));
}
function t2(text) {
    return new TextRun({ text, font: "Calibri", size: 22 });
}
function hl(text) {
    return t(text, { highlight: "yellow" });
}
function mainBullet(children, spaceAfter = 120) {
    return new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { after: spaceAfter },
        children
    });
}
function subBullet(children, spaceAfter = 60) {
    return new Paragraph({
        numbering: { reference: "bullets", level: 1 },
        spacing: { after: spaceAfter },
        children
    });
}

const border = { style: BorderStyle.SINGLE, size: 1, color: "000000" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 40, bottom: 40, left: 80, right: 80 };
const colWidths = [1600, 1400, 1400, 800, 1000, 1700];
const tableWidth = colWidths.reduce((a, b) => a + b, 0);

function headerCell(text, width) {
    return new TableCell({
        borders,
        width: { size: width, type: WidthType.DXA },
        margins: cellMargins,
        shading: { fill: "D9E2F3", type: ShadingType.CLEAR },
        children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [t(text, { bold: true })]
        })]
    });
}
function dataCell(text, width) {
    return new TableCell({
        borders,
        width: { size: width, type: WidthType.DXA },
        margins: cellMargins,
        children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [t(text)]
        })]
    });
}

const children = [
    new Paragraph({
        spacing: { after: 240 },
        children: [t("Evaluation Assumptions", { bold: true, underline: {} })]
    }),

    mainBullet([t("Order ID: ", { bold: true }), t("41000075593")]),
    mainBullet([t("Project ID: ", { bold: true }), t("04-20-62600 (SS-6004AL)")]),
    mainBullet([
        t("GPS Coordinates: ", { bold: true }),
        new ExternalHyperlink({
            link: "https://www.google.com/maps?q=35.272548,-77.924074",
            children: [t("35.272548, -77.924074", { color: "0563C1", underline: {} })]
        }),
        t(" to "),
        new ExternalHyperlink({
            link: "https://www.google.com/maps?q=35.273209,-77.934366",
            children: [t("35.273209, -77.934366", { color: "0563C1", underline: {} })]
        })
    ]),
    mainBullet([t("County / Division: ", { bold: true }), t("Wayne County / Division 4")]),
    mainBullet([t("Location: ", { bold: true }), t("SR 2050 (Slick Rock Road) between SR 1912 (Gertrude Grady Road) and SR 2051 (Rock Road)")]),

    mainBullet([t("Countermeasure: ", { bold: true }), t("Install warning signs (curve, turn, large arrows, dead end pennants) and speed limit signing.")], 60),
    subBullet([hl("[Installed Turn (W1-1) and Curve (W1-2) warning signs with advisory speed plaques along SR 2050]")]),
    subBullet([hl("[Installed One-Direction Large Arrow (W1-6) signs at curves along SR 2050]")]),
    subBullet([hl("[Installed DEAD END pennants on dead end side roads along SR 2050]")]),
    subBullet([t("Speed limit lowered from statutory 55 MPH to 35 MPH with Speed Limit (R2-1) signs installed along SR 2050")]),
    subBullet([hl("[Verify specific countermeasure details via project plans and imagery review]")], 120),

    mainBullet([t("Total Cost Estimate: ", { bold: true }), t("$6,000")]),

    mainBullet([t("Project Completion: ", { bold: true }), t("11/19/2021 per final review memo")], 60),
    subBullet([hl("[According to historical aerials in Google Earth, project was completed between ___ and ___.]")]),
    subBullet([hl("[Google Street View shows project was completed between ___ and ___.]")]),
    subBullet([hl("[NearMap shows project was completed between ___ and ___.]")], 120),

    mainBullet([t("Time Periods", { bold: true })]),
    new Table({
        width: { size: tableWidth, type: WidthType.DXA },
        columnWidths: colWidths,
        indent: { size: 720, type: WidthType.DXA },
        rows: [
            new TableRow({
                children: [
                    headerCell("Period", colWidths[0]),
                    headerCell("Start Date", colWidths[1]),
                    headerCell("End Date", colWidths[2]),
                    headerCell("Years", colWidths[3]),
                    headerCell("Months", colWidths[4]),
                    headerCell("Total", colWidths[5])
                ]
            }),
            new TableRow({
                children: [
                    dataCell("Before", colWidths[0]),
                    dataCell("4/1/2017", colWidths[1]),
                    dataCell("9/30/2021", colWidths[2]),
                    dataCell("4", colWidths[3]),
                    dataCell("6", colWidths[4]),
                    dataCell("4 yrs 6 mos", colWidths[5])
                ]
            }),
            new TableRow({
                children: [
                    dataCell("Construction", colWidths[0]),
                    dataCell("10/1/2021", colWidths[1]),
                    dataCell("12/31/2021", colWidths[2]),
                    dataCell("0", colWidths[3]),
                    dataCell("3", colWidths[4]),
                    dataCell("3 mos", colWidths[5])
                ]
            }),
            new TableRow({
                children: [
                    dataCell("After", colWidths[0]),
                    dataCell("1/1/2022", colWidths[1]),
                    dataCell("6/30/2026", colWidths[2]),
                    dataCell("4", colWidths[3]),
                    dataCell("6", colWidths[4]),
                    dataCell("4 yrs 6 mos", colWidths[5])
                ]
            })
        ]
    }),
    new Paragraph({ spacing: { after: 120 }, children: [] }),

    mainBullet([t("Target Crashes: ", { bold: true }), t("Lane departure crashes along the section (Ran Off Road Left/Right/Straight, Fixed Object, Overturn/Rollover, Head-On, Sideswipe Opposite Direction)")]),

    mainBullet([t("Project Dev Crash Summary: ", { bold: true }), t("2 total crashes (1 fatal, 1 PDO); Total Crash CR = 0.3; Severity Index = 38.90 along the section from 8/1/2015 to 7/31/2020")]),

    mainBullet([t("Notes:", { bold: true })], 60),
    subBullet([t("A three month construction period from 10/1/2021 to 12/31/2021 is used. The final review memo lists a construction begin date of 11/8/2021 and a construction completion date of 11/19/2021, with the final field review on 12/28/2021.")]),
    subBullet([t("Project was requested by the investigation of a fatal crash that occurred on 6/11/2020. The fatal crash (fixed object at MP 0.997) is within the study section and falls within the proposed before period.")]),
    subBullet([t("Section evaluation along SR 2050 from MP 0.797 (SR 1912) to MP 1.517 (Rock Road), 0.72 mile, matching TEAAS study 200611019CA from project development.")]),
    subBullet([t("The project description and project development strip report list Rock Road as SR 1051. A TEAAS features report for SR 2051 confirms an at grade intersection with SR 2050, matching the crash location maps, so SR 2051 is used for the evaluation.")]),
    subBullet([t("Plans developed by Division 4.")])
];

doc.Document.View = undefined; // no-op safeguard
doc.sections = undefined;

const finalDoc = new Document({
    styles: { default: { document: { run: { font: "Calibri", size: 22 } } } },
    numbering: {
        config: [{
            reference: "bullets",
            levels: [
                { level: 0, format: LevelFormat.BULLET, text: "\uF0B7", alignment: AlignmentType.LEFT,
                  style: { run: { font: "Symbol" }, paragraph: { indent: { left: 720, hanging: 360 } } } },
                { level: 1, format: LevelFormat.BULLET, text: "o", alignment: AlignmentType.LEFT,
                  style: { run: { font: "Courier New" }, paragraph: { indent: { left: 1440, hanging: 360 } } } }
            ]
        }]
    },
    sections: [{
        properties: {
            page: { size: { width: 12240, height: 15840 },
                    margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
        },
        children
    }]
});

Packer.toBuffer(finalDoc).then(buffer => {
    const outPath = "/mnt/user-data/outputs/Assumptions Email - 04-20-62600 (SS-6004AL).docx";
    fs.writeFileSync(outPath, buffer);
    console.log("Created:", outPath);
});
