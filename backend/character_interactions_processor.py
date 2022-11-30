import json

import numpy as np

import backend.nlp as nlp

JSON_DIRECTORY = "timelines/"


class CharacterInteractionsProcessor:

    def __init__(self, chapter_regex: str, nb_sections: int, percentile: int, narrator: str, quiet: bool, pruned: bool):
        self.pruned = pruned
        self.quiet = quiet
        self.narrator = narrator
        self.percentile = percentile
        self.nb_sections = nb_sections
        self.chapter_regex = chapter_regex

        self.sections = []
        self.unnormalised_matrices = []
        self.normalised_matrices = []
        self.characters_timeline = []
        self.metadata = {}

    def preprocess_text(self, text: str):
        if self.chapter_regex:
            if not self.quiet:
                print("Splitting book into chapters...")
            timeline = list(self.chapter_regex.split(text))
            timeline.pop(0)
            self.nb_sections = len(timeline)
        else:
            # Splits by paragraph, then joins paragraphs back up into NUM_SPLITS
            # sections
            if not self.quiet:
                print("Splitting book into {0} sections...".format(self.nb_sections))
            paragraphs = text.split("\n")
            num_sections = min(self.nb_sections, len(paragraphs))
            k, m = divmod(len(paragraphs), self.nb_sections)
            # This combines paragraphs into NUM_SPLIT sections and then restores
            # the paragraph structure
            timeline = ["\n".join(paragraphs[i * k + min(i,
                                                         m): (i + 1) * k + min(i + 1,
                                                                               m)]) for i in range(num_sections)]
            filter(lambda ps: ("".join(ps).strip() != ""), timeline)
        if not self.quiet:
            print("Cleaning text...")
        for segment in timeline:
            segment = segment.rstrip()
            segment = segment.replace("\n", " ")
            segment = segment.replace("\r", " ")
            self.sections.append(segment)
        if not self.quiet:
            print("Finished cleaning and splitting text...")

    def _calculate_threshold(self, values: np.ndarray) -> float:
        values = values[values > 0]
        return np.percentile(values, self.percentile)

    def prune(self):
        if not self.quiet:
            print("Pruning timeline matrices...")
        characters_interactions = {
            ch: self.unnormalised_matrices[-1][:, self.characters_timeline[-1].index(ch)].sum()
            for ch in self.characters_timeline[-1]
        }
        threshold = self._calculate_threshold(np.fromiter(characters_interactions.values(), dtype=int))
        if not self.quiet:
            print("Threshold: ", threshold)
        unimportant_characters = [ch for (ch, x) in characters_interactions.items() if x < threshold]

        self._prune_matrices(unimportant_characters)
        interactions_overall, interactions_per_character = self._prune_metadata(unimportant_characters)

        return interactions_overall, interactions_per_character

    def _prune_matrices(self, unimportant_characters: list[str]):
        for i in range(len(self.unnormalised_matrices)):
            for character in [ch for ch in self.characters_timeline[i] if ch in unimportant_characters]:
                j = self.characters_timeline[i].index(character)
                self.unnormalised_matrices[i] = np.delete(
                    np.delete(self.unnormalised_matrices[i], j, axis=0),
                    j, axis=1
                )
                self.characters_timeline[i].pop(j)

    def sort_matrix(self, i):
        matrix = np.array(self.normalised_matrices[i])
        np_chars = np.array(self.characters_timeline[i])
        indices = np.argsort(-np.sum(matrix, 0))
        ordered_matrix = matrix[:, indices]
        ordered_matrix = ordered_matrix[indices, :]
        ordered_characters = np_chars[indices]
        self.normalised_matrices[i] = ordered_matrix
        self.characters_timeline[i] = list(ordered_characters)

    def _prune_metadata(self, unimportant_characters: list[str]):
        interactions_overall = self.metadata["first interactions overall"]
        interactions_per_character = self.metadata["first interactions per char"]
        for c in unimportant_characters:
            if c in interactions_overall:
                del interactions_overall[c]
            if c in interactions_per_character:
                del interactions_per_character[c]
            for key in list(interactions_per_character.keys()):
                if c in interactions_per_character[key]:
                    del interactions_per_character[key][c]
                    if not interactions_per_character[key]:
                        del interactions_per_character[key]
        return interactions_overall, interactions_per_character

    def update_names_metadata(self, mg):
        curr_metadata = "first interactions per char"
        for (name, value) in self.metadata["first interactions per char"].copy().items():
            new_name = mg.character_dict[name]
            if new_name != name:
                self.metadata[curr_metadata][new_name] = self.metadata[curr_metadata].pop(name)
            for (name2, interaction) in value.copy().items():
                new_name2 = mg.character_dict[name2]
                if new_name2 != name2 and name2 in self.metadata[curr_metadata][new_name]:
                    self.metadata[curr_metadata][new_name][new_name2] = self.metadata[curr_metadata][new_name].pop(
                        name2)

        curr_metadata = "first interactions overall"
        for (name, interaction) in self.metadata[curr_metadata].copy().items():
            new_name = mg.character_dict[name]
            self.metadata[curr_metadata][new_name] = self.metadata[curr_metadata].pop(name)
            int_with = self.metadata[curr_metadata][new_name]["with"]
            self.metadata[curr_metadata][new_name]["with"] = mg.character_dict[int_with]

    @staticmethod
    def normalise_matrix(matrix: np.ndarray):
        for i in range(len(matrix)):
            row_sum = sum(matrix[i])
            for j in range(len(matrix[i])):
                matrix[i][j] = (matrix[i][j] / row_sum) if row_sum != 0 else 0
        return matrix

    def generate_timeline_json(self, title: str):
        file_path = JSON_DIRECTORY + "{}_analysis.json".format(title.replace(' ', '_'))
        json_contents = {"book": title.replace('_', ' ').title(),
                         "num_sections": self.nb_sections,
                         "sections": []
                         }

        matrix_generator = nlp.InteractionsCounter(self.narrator)
        for (i, section) in enumerate(self.sections):
            if not self.quiet:
                print("Analysing section {} of {}...".format(i + 1, self.nb_sections))
            interactions, characters = matrix_generator(section)
            self.unnormalised_matrices.append(interactions)
            self.characters_timeline.append(characters)
        self.metadata = matrix_generator.get_metadata()

        if self.pruned:
            self.prune()

        self.normalised_matrices = list(map(self.normalise_matrix, self.unnormalised_matrices))
        for i in range(len(self.characters_timeline)):
            for j in range(len(self.characters_timeline[i])):
                self.characters_timeline[i][j] = matrix_generator.character_dict[self.characters_timeline[i][j]]
            self.sort_matrix(i)
            json_contents["sections"].append({
                "names": self.characters_timeline[i],
                "matrix": self.normalised_matrices[i].tolist()
            })
        self.update_names_metadata(matrix_generator)
        json_contents["first_interactions_between_characters"] = self.metadata["first interactions per char"]
        json_contents["first_interactions_overall"] = self.metadata["first interactions overall"]
        with open(file_path, "w", newline='\r\n') as f:
            f.write(json.dumps(json_contents, indent=2))
        if not self.quiet:
            print("Done! Analysis saved at {}.".format(file_path))

    def process(self, title: str, text: str):
        self.preprocess_text(text)
        self.generate_timeline_json(title)
