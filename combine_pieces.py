import os
import argparse

def combine_pieces(pieces_folder, output_file):
    piece_files = sorted(os.listdir(pieces_folder), key=lambda x: int(x.split('_')[1].split('.')[0]))
    with open(output_file, "wb") as outfile:
        for piece_file in piece_files:
            piece_path = os.path.join(pieces_folder, piece_file)
            with open(piece_path, "rb") as infile:
                outfile.write(infile.read())
            print(f"Piece {piece_file} added to {output_file}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine pieces into a complete file.")
    parser.add_argument("pieces_folder", help="Folder containing the piece files.")
    parser.add_argument("output_file", help="Output file path.")
    args = parser.parse_args()

    combine_pieces(args.pieces_folder, args.output_file)