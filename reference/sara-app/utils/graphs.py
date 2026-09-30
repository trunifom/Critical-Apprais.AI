
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import io


class PRISMAFlowchart:
    def __init__(self, review_counts: dict):
        self.data = review_counts

    def get_png_bytes(self):
  
        # Prepare subcategory text for abstract exclusions
        d_title = "Excluded at title/abstract:"
        d_count = str(self.data['excluded_title_abstract'])
        d_subcat_lines = []
        if 'excluded_title_abstract' in self.data:
            ft = self.data['excluded_title_abstract']
            if ft:
                d_subcat_lines = [f"- {reason.replace('_', ' ').title()}: {count}" for reason, count in ft.items()]
        d_label = d_title
        if d_subcat_lines:
            d_label += "\n" + "\n".join(d_subcat_lines)

        # Prepare subcategory text for full-text exclusions
        f_title = "Excluded full-text"
        f_subcat_lines = []
        if 'excluded_full_text' in self.data:
            ft = self.data['excluded_full_text']
            if ft:
                f_subcat_lines = [f"- {reason.replace('_', ' ').title()}: {count}" for reason, count in ft.items()]
        f_label = f_title
        if f_subcat_lines:
            f_label += "\n" + "\n".join(f_subcat_lines)


        x_shift = 1.0
        # Check if full text review is available
        has_full_text = 'full_text_assessed' in self.data and self.data['full_text_assessed'] is not None

        # Node definitions: (label, (x, y), is_exclusion)
        nodes = {
            "A": (f"Records imported:\n{self.data['total_imported']}", (0.0 + x_shift, 9.0), False),
            "C": (f"Title/abstract screened:\n{self.data['title_abstract_screened']}", (0.0 + x_shift, 7.0), False),
            "B": (f"Duplicates removed:\n{self.data['duplicates_removed']}", (2.5 + x_shift, 9.0), False),
            "D": (d_label, (2.5 + x_shift, 7.0), True),
        }
        arrows = [
            ("A", "C"),
            ("A", "B"),
            ("C", "D"),
        ]
        if has_full_text:
            nodes["E"] = (f"Full-text assessed:\n{self.data['full_text_assessed']}", (0.0 + x_shift, 5.0), False)
            nodes["F"] = (f_label, (2.5 + x_shift, 5.0), True)
            nodes["G"] = (f"Included in review:\n{self.data['included_in_review']}", (0.0 + x_shift, 1.0), False)
            arrows += [
                ("C", "E"),
                ("E", "F"),
                ("E", "G"),
            ]

        fig, ax = plt.subplots(figsize=(7, 8))  # less wide and less tall
        ax.axis('off')
        box_width = 2.0
        box_height = 1.3
        line_spacing = 0.22  # more space between lines
        # Draw squares and text
        for key, (label, (x, y), is_exclusion) in nodes.items():
            lines = label.split('\n')
            n_lines = len(lines)
            height = box_height + 0.2 * max(0, n_lines - 2)
            rect = patches.Rectangle((x - box_width/2, y - height/2), box_width, height,
                                    linewidth=2, edgecolor='black', facecolor='none')
            ax.add_patch(rect)
            # Draw main title (first line, bold)
            ax.text(x, y + (line_spacing * (n_lines-1)), lines[0], ha='center', va='top', fontsize=10, fontweight='bold', wrap=True)
            if n_lines > 1:
                if is_exclusion:
                    for i, subline in enumerate(lines[1:]):
                        ax.text(x - box_width/2 + 0.08, y + (line_spacing * (n_lines-2-i)), subline, ha='left', va='top', fontsize=10, fontweight='normal', wrap=True)
                else:
                    for i, subline in enumerate(lines[1:]):
                        ax.text(x, y + (line_spacing * (n_lines-2-i)), subline, ha='center', va='top', fontsize=10, fontweight='normal', wrap=True)
        for src, dst in arrows:
            x0, y0 = nodes[src][1]
            x1, y1 = nodes[dst][1]
            src_label = nodes[src][0]
            dst_label = nodes[dst][0]
            src_n_lines = src_label.count('\n') + 1
            dst_n_lines = dst_label.count('\n') + 1
            src_height = box_height + 0.2 * max(0, src_n_lines - 2)
            dst_height = box_height + 0.2 * max(0, dst_n_lines - 2)
            if x0 == x1:  # vertical
                ax.annotate('', xy=(x1, y1 + dst_height/2), xytext=(x0, y0 - src_height/2),
                            arrowprops=dict(arrowstyle='->', lw=2))
            elif x1 > x0:  # rightward (exclusion)
                ax.annotate('', xy=(x1 - box_width/2, y1), xytext=(x0 + box_width/2, y0),
                            arrowprops=dict(arrowstyle='->', lw=2))
            elif x1 < x0:  # leftward (shouldn't happen, but for completeness)
                ax.annotate('', xy=(x1 + box_width/2, y1), xytext=(x0 - box_width/2, y0),
                            arrowprops=dict(arrowstyle='->', lw=2))
        ax.set_xlim(0, 5.5)
        ax.set_ylim(0, 10)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
